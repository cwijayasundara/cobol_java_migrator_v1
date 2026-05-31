package com.cobolmodernizer.cobol;

import com.cobolmodernizer.cobol.json.RelationshipJson;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
import org.junit.jupiter.api.Test;

import java.io.File;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class CicsSqlScannerTest {
    private final CobolIoScanner s = new CobolIoScanner(CobolSourceFormatEnum.FIXED);

    private static RelationshipJson byCmd(List<RelationshipJson> r, String kind, String cmdOrOp) {
        return r.stream().filter(x -> x.kind().equals(kind)
                && (cmdOrOp.equals(x.metadata().get("command"))
                    || cmdOrOp.equals(x.metadata().get("operation"))))
                .findFirst().orElse(null);
    }

    @Test
    void cicsReadIsReadIntentRewriteIsWriteIntent() {
        List<RelationshipJson> rels =
            s.scanCics(new File("src/test/resources/cobol/cicsview.cbl"), "CICSVIEW", "cicsview.cbl");
        RelationshipJson read = byCmd(rels, "EXECUTES_CICS", "READ");
        assertNotNull(read);
        assertEquals("LIT-ACCTFILENAME", read.metadata().get("resource"));
        assertEquals("read", read.metadata().get("intent"));
        RelationshipJson rewrite = byCmd(rels, "EXECUTES_CICS", "REWRITE");
        assertNotNull(rewrite);
        assertEquals("write", rewrite.metadata().get("intent"));
    }

    @Test
    void sqlSelectIsReadUpdateIsWrite() {
        List<RelationshipJson> rels =
            s.scanSql(new File("src/test/resources/cobol/sqlupd.cbl"), "SQLUPD", "sqlupd.cbl");
        RelationshipJson sel = byCmd(rels, "EXECUTES_SQL", "SELECT");
        assertNotNull(sel);
        assertEquals("CARDDEMO.TRANSACTION_TYPE", sel.metadata().get("resource"));
        assertEquals("read", sel.metadata().get("intent"));
        RelationshipJson upd = byCmd(rels, "EXECUTES_SQL", "UPDATE");
        assertNotNull(upd);
        assertEquals("write", upd.metadata().get("intent"));
    }
}
