package com.cobolmodernizer.cobol;

import com.cobolmodernizer.cobol.json.DataItemJson;
import com.cobolmodernizer.cobol.json.RelationshipJson;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** v2 data-flow walker: DataItem nodes + MOVES_TO/GO_TO edges, plus IO/CICS/SQL via CobolIoScanner. */
public final class DataFlowWalker {
    private final CobolSourceFormatEnum format;
    private final CobolIoScanner io;

    public DataFlowWalker(CobolSourceFormatEnum format) {
        this.format = format;
        this.io = new CobolIoScanner(format);
    }

    private static final Pattern LEVEL =
        Pattern.compile("(?i)^\\s*(\\d{2})\\s+([A-Z0-9][A-Z0-9-]*)");
    private static final Pattern PIC =
        Pattern.compile("(?i)\\b(?:PIC|PICTURE)\\s+(?:IS\\s+)?([X9SVAPZ()0-9V.,/+-]+)");
    private static final Pattern USAGE =
        Pattern.compile("(?i)\\b(?:USAGE\\s+(?:IS\\s+)?)?(COMP-3|COMP-4|COMP-5|COMP|BINARY|PACKED-DECIMAL|DISPLAY)\\b");
    private static final Pattern OCCURS =
        Pattern.compile("(?i)\\bOCCURS\\s+(\\d+)");
    private static final Pattern REDEF =
        Pattern.compile("(?i)\\bREDEFINES\\s+([A-Z0-9][A-Z0-9-]*)");
    private static final Pattern MOVE =
        Pattern.compile("(?i)\\bMOVE\\s+([A-Z0-9][A-Z0-9-]*)\\s+TO\\s+(.+)");
    private static final Pattern WORD =
        Pattern.compile("(?i)([A-Z0-9][A-Z0-9-]*)");
    private static final Pattern GOTO =
        Pattern.compile("(?i)\\bGO\\s+TO\\s+([A-Z0-9][A-Z0-9-]*)");
    private static final Pattern PARA_HDR =
        Pattern.compile("(?i)^\\s{0,11}([A-Z0-9][A-Z0-9-]*)\\s*\\.\\s*$");

    private boolean isComment(String line) {
        return format == CobolSourceFormatEnum.FIXED && line.length() > 6
                && (line.charAt(6) == '*' || line.charAt(6) == '/');
    }

    private List<String> read(File f) {
        try { return Files.readAllLines(f.toPath(), StandardCharsets.ISO_8859_1); }
        catch (Exception e) { return List.of(); }
    }

    public List<DataItemJson> dataItems(File file, String progId, String relPath) {
        List<DataItemJson> out = new ArrayList<>();
        Deque<int[]> stack = new ArrayDeque<>();          // {level, index-into-out}
        int lineNo = 0;
        for (String raw : read(file)) {
            lineNo++;
            if (isComment(raw)) continue;
            Matcher lm = LEVEL.matcher(raw);
            if (!lm.find()) continue;
            int level = Integer.parseInt(lm.group(1));
            if (level == 88) continue;                    // 88-level condition names are not storage
            String name = lm.group(2).toUpperCase();
            Matcher pm = PIC.matcher(raw);   String pic = pm.find() ? pm.group(1) : null;
            Matcher um = USAGE.matcher(raw); String usage = um.find() ? um.group(1).toUpperCase() : null;
            Matcher om = OCCURS.matcher(raw); int occurs = om.find() ? Integer.parseInt(om.group(1)) : 0;
            Matcher dm = REDEF.matcher(raw); String redef = dm.find() ? dm.group(1).toUpperCase() : null;
            while (!stack.isEmpty() && stack.peek()[0] >= level) stack.pop();
            String parent = stack.isEmpty() ? null
                    : progId + "." + out.get(stack.peek()[1]).simpleName();
            out.add(new DataItemJson("DataItem", progId + "." + name, name, relPath,
                    lineNo, lineNo, false, level, pic, usage, redef, occurs, parent));
            stack.push(new int[]{level, out.size() - 1});
        }
        return out;
    }

    public List<RelationshipJson> dataFlowEdges(File file, String progId, String relPath) {
        List<RelationshipJson> out = new ArrayList<>();
        String curPara = null; int lineNo = 0;
        for (String raw : read(file)) {
            lineNo++;
            if (isComment(raw)) continue;
            Matcher ph = PARA_HDR.matcher(raw);
            if (ph.find()) { curPara = ph.group(1).toUpperCase(); continue; }
            Matcher mm = MOVE.matcher(raw);
            if (mm.find()) {
                String src = mm.group(1).toUpperCase();
                Matcher wm = WORD.matcher(mm.group(2));
                while (wm.find()) {
                    String tgt = wm.group(1).toUpperCase();
                    if (tgt.equals("TO")) continue;
                    out.add(new RelationshipJson(progId + "." + src, progId + "." + tgt,
                            "MOVES_TO", relPath, lineNo, Map.of("line", lineNo)));
                    break;  // first receiver; MOVE a TO b c handled by re-scan if needed
                }
            }
            Matcher gm = GOTO.matcher(raw);
            if (gm.find() && curPara != null) {
                out.add(new RelationshipJson(progId + "." + curPara,
                        progId + "." + gm.group(1).toUpperCase(),
                        "GO_TO", relPath, lineNo, Map.of()));
            }
        }
        return out;
    }

    /** All v2 edges for a program: IO + CICS + SQL + MOVES_TO + GO_TO. */
    public List<RelationshipJson> allEdges(File file, String progId, String relPath) {
        List<RelationshipJson> out = new ArrayList<>();
        out.addAll(io.scanIo(file, progId, relPath));
        out.addAll(io.scanCics(file, progId, relPath));
        out.addAll(io.scanSql(file, progId, relPath));
        out.addAll(dataFlowEdges(file, progId, relPath));
        return out;
    }
}
