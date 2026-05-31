package com.cobolmodernizer.cobol;

import com.cobolmodernizer.cobol.json.RelationshipJson;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Line-oriented scanner for the v2 data-flow / IO signals. Deterministic and
 * ProLeap-ASG-independent so a partial parse still yields IO edges (graceful
 * degradation). Resource on each edge is the ddname from ASSIGN TO, joining to
 * the mainframe dataset name (e.g. ACCTDAT/CARDDAT/TRANSACT).
 */
public final class CobolIoScanner {
    private final CobolSourceFormatEnum format;

    public CobolIoScanner(CobolSourceFormatEnum format) { this.format = format; }

    private record FileDef(String logical, String ddname, String resourceType, String mode) {}

    private static final Pattern SELECT =
        Pattern.compile("(?i)\\bSELECT\\s+([A-Z0-9][A-Z0-9-]*)\\s+ASSIGN\\s+TO\\s+([A-Z0-9][A-Z0-9-]*)");
    private static final Pattern ORG =
        Pattern.compile("(?i)\\bORGANIZATION\\s+(?:IS\\s+)?(INDEXED|SEQUENTIAL|RELATIVE)");
    private static final Pattern ACCESS =
        Pattern.compile("(?i)\\bACCESS\\s+MODE\\s+(?:IS\\s+)?(SEQUENTIAL|RANDOM|DYNAMIC)");
    private static final Pattern FD =
        Pattern.compile("(?i)^\\s*FD\\s+([A-Z0-9][A-Z0-9-]*)");
    private static final Pattern REC01 =
        Pattern.compile("(?i)^\\s*01\\s+([A-Z0-9][A-Z0-9-]*)");
    private static final Pattern READ =
        Pattern.compile("(?i)\\bREAD\\s+([A-Z0-9][A-Z0-9-]*)");
    private static final Pattern WRITE =
        Pattern.compile("(?i)\\b(?:WRITE|REWRITE)\\s+([A-Z0-9][A-Z0-9-]*)");

    private boolean isComment(String line) {
        return format == CobolSourceFormatEnum.FIXED && line.length() > 6
                && (line.charAt(6) == '*' || line.charAt(6) == '/');
    }

    private List<String> read(File file) {
        try {
            return Files.readAllLines(file.toPath(), StandardCharsets.ISO_8859_1);
        } catch (Exception ignored) {
            return List.of();  // graceful: no source -> no IO edges
        }
    }

    public List<RelationshipJson> scanIo(File file, String progId, String relPath) {
        List<RelationshipJson> rels = new ArrayList<>();
        List<String> lines = read(file);

        // Pass 1: SELECT ... ASSIGN TO ... (+ following ORGANIZATION/ACCESS lines)
        Map<String, FileDef> byLogical = new LinkedHashMap<>();
        String pendingLogical = null, pendingDd = null, org = "SEQUENTIAL", mode = "sequential";
        for (String raw : lines) {
            if (isComment(raw)) continue;
            Matcher sm = SELECT.matcher(raw);
            if (sm.find()) {
                if (pendingLogical != null)
                    byLogical.put(pendingLogical, defOf(pendingLogical, pendingDd, org, mode));
                pendingLogical = sm.group(1).toUpperCase();
                pendingDd = sm.group(2).toUpperCase();
                org = "SEQUENTIAL"; mode = "sequential";
                continue;
            }
            if (pendingLogical != null) {
                Matcher om = ORG.matcher(raw);
                if (om.find()) org = om.group(1).toUpperCase();
                Matcher am = ACCESS.matcher(raw);
                if (am.find()) mode = am.group(1).toLowerCase();
            }
        }
        if (pendingLogical != null)
            byLogical.put(pendingLogical, defOf(pendingLogical, pendingDd, org, mode));

        // Pass 2: FD <logical> then next 01 <record> binds record -> ddname
        Map<String, String> recordToDd = new HashMap<>();
        String fdLogical = null;
        for (String raw : lines) {
            if (isComment(raw)) continue;
            Matcher fm = FD.matcher(raw);
            if (fm.find()) {
                String logical = fm.group(1).toUpperCase();
                FileDef d = byLogical.get(logical);
                fdLogical = (d != null) ? d.ddname() : logical;
                continue;
            }
            if (fdLogical != null) {
                Matcher rm = REC01.matcher(raw);
                if (rm.find()) { recordToDd.put(rm.group(1).toUpperCase(), fdLogical); fdLogical = null; }
            }
        }

        // Pass 3: READ/WRITE verbs -> READS/WRITES edges keyed on ddname
        int lineNo = 0;
        for (String raw : lines) {
            lineNo++;
            if (isComment(raw)) continue;
            Matcher rd = READ.matcher(raw);
            if (rd.find()) {
                String logical = rd.group(1).toUpperCase();
                FileDef d = byLogical.get(logical);
                String dd = (d != null) ? d.ddname() : logical;
                String rtype = (d != null) ? d.resourceType() : "FILE";
                String md = (d != null) ? d.mode() : "sequential";
                rels.add(new RelationshipJson(progId, dd, "READS", relPath, lineNo,
                        Map.of("resource", dd, "resourceType", rtype, "mode", md)));
            }
            Matcher wr = WRITE.matcher(raw);
            if (wr.find()) {
                String rec = wr.group(1).toUpperCase();
                String dd = recordToDd.getOrDefault(rec, rec);
                FileDef d = byLogical.values().stream()
                        .filter(x -> x.ddname().equals(dd)).findFirst().orElse(null);
                String rtype = (d != null) ? d.resourceType() : "FILE";
                String md = (d != null) ? d.mode() : "sequential";
                rels.add(new RelationshipJson(progId, dd, "WRITES", relPath, lineNo,
                        Map.of("resource", dd, "resourceType", rtype, "mode", md)));
            }
        }
        return rels;
    }

    private static FileDef defOf(String logical, String dd, String org, String mode) {
        String rtype = "INDEXED".equals(org) ? "VSAM" : "FILE";
        return new FileDef(logical, dd == null ? logical : dd, rtype, mode);
    }

    // ---- EXEC CICS / EXEC SQL intent scanning ----

    private static final Pattern CICS_VERB =
        Pattern.compile("(?i)\\bEXEC\\s+CICS\\s+([A-Z]+)");
    private static final Pattern CICS_RES =
        Pattern.compile("(?i)\\b(?:DATASET|FILE)\\s*\\(\\s*([A-Z0-9][A-Z0-9-]*)");
    private static final Map<String, String> CICS_INTENT = Map.of(
        "READ", "read", "STARTBR", "read", "READNEXT", "read", "READPREV", "read",
        "RECEIVE", "read", "WRITE", "write", "REWRITE", "write", "DELETE", "write",
        "SEND", "write");

    private static final Pattern SQL_VERB =
        Pattern.compile("(?i)\\b(SELECT|INSERT|UPDATE|DELETE|FETCH)\\b");
    private static final Pattern SQL_FROM =
        Pattern.compile("(?i)\\b(?:FROM|INTO|UPDATE|DELETE\\s+FROM)\\s+([A-Z0-9_][A-Z0-9_.]*)");
    private static final Map<String, String> SQL_INTENT = Map.of(
        "SELECT", "read", "FETCH", "read",
        "INSERT", "write", "UPDATE", "write", "DELETE", "write");

    /** Collect each EXEC <opener> ... END-EXEC block as {joinedBlockText, firstLineNo}. */
    private List<String[]> execBlocks(File file, String opener) {
        List<String[]> out = new ArrayList<>();
        StringBuilder buf = null;
        int start = 0, n = 0;
        for (String raw : read(file)) {
            n++;
            if (isComment(raw)) continue;
            String up = raw.toUpperCase();
            if (buf == null && up.contains(opener)) { buf = new StringBuilder(raw); start = n; }
            else if (buf != null) buf.append(' ').append(raw);
            if (buf != null && up.contains("END-EXEC")) {
                out.add(new String[]{buf.toString(), String.valueOf(start)});
                buf = null;
            }
        }
        return out;
    }

    public List<RelationshipJson> scanCics(File file, String progId, String relPath) {
        List<RelationshipJson> rels = new ArrayList<>();
        for (String[] blk : execBlocks(file, "EXEC CICS")) {
            Matcher vm = CICS_VERB.matcher(blk[0]);
            if (!vm.find()) continue;
            String cmd = vm.group(1).toUpperCase();
            String intent = CICS_INTENT.get(cmd);
            if (intent == null) continue;  // HANDLE/RETURN/XCTL/SYNCPOINT etc. are not data IO
            Matcher rm = CICS_RES.matcher(blk[0]);
            String res = rm.find() ? rm.group(1).toUpperCase() : cmd;
            Map<String, Object> meta = new LinkedHashMap<>();
            meta.put("resource", res); meta.put("command", cmd); meta.put("intent", intent);
            rels.add(new RelationshipJson(progId, res, "EXECUTES_CICS",
                    relPath, Integer.valueOf(blk[1]), meta));
        }
        return rels;
    }

    public List<RelationshipJson> scanSql(File file, String progId, String relPath) {
        List<RelationshipJson> rels = new ArrayList<>();
        for (String[] blk : execBlocks(file, "EXEC SQL")) {
            String body = blk[0];
            if (body.toUpperCase().contains("INCLUDE")) continue; // EXEC SQL INCLUDE copybook, not data IO
            Matcher vm = SQL_VERB.matcher(body);
            if (!vm.find()) continue;
            String op = vm.group(1).toUpperCase();
            String intent = SQL_INTENT.getOrDefault(op, "read");
            Matcher fm = SQL_FROM.matcher(body);
            String res = fm.find() ? fm.group(1).toUpperCase() : op;
            Map<String, Object> meta = new LinkedHashMap<>();
            meta.put("resource", res); meta.put("operation", op); meta.put("intent", intent);
            rels.add(new RelationshipJson(progId, res, "EXECUTES_SQL",
                    relPath, Integer.valueOf(blk[1]), meta));
        }
        return rels;
    }
}
