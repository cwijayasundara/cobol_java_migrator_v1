package com.cobolmodernizer.cobol;

import com.cobolmodernizer.cobol.json.DataItemJson;
import com.cobolmodernizer.cobol.json.RelationshipJson;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
import org.junit.jupiter.api.Test;

import java.io.File;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class DataItemTest {
    private final DataFlowWalker w = new DataFlowWalker(CobolSourceFormatEnum.FIXED);
    private final File f = new File("src/test/resources/cobol/acctread.cbl");

    @Test
    void extractsDataItemsWithLevelPictureUsage() {
        List<DataItemJson> items = w.dataItems(f, "ACCTREAD", "acctread.cbl");
        DataItemJson bal = items.stream()
            .filter(d -> d.qualifiedName().equals("ACCTREAD.OUT-ACCT-BAL"))
            .findFirst().orElse(null);
        assertNotNull(bal);
        assertEquals(5, bal.level());
        assertEquals("S9(10)V99", bal.picture());
        assertEquals("COMP-3", bal.usage());
        assertEquals("ACCTREAD.OUT-ACCT-REC", bal.parentQname());
    }

    @Test
    void extractsMovesToAndGoTo() {
        List<RelationshipJson> rels = w.dataFlowEdges(f, "ACCTREAD", "acctread.cbl");
        assertTrue(rels.stream().anyMatch(r -> r.kind().equals("MOVES_TO")
                && r.sourceQname().equals("ACCTREAD.FD-ACCT-ID")
                && r.targetQname().equals("ACCTREAD.OUT-ACCT-ID")));
        assertTrue(rels.stream().anyMatch(r -> r.kind().equals("GO_TO")
                && r.sourceQname().equals("ACCTREAD.1000-MAIN")
                && r.targetQname().equals("ACCTREAD.9000-EXIT")));
    }
}
