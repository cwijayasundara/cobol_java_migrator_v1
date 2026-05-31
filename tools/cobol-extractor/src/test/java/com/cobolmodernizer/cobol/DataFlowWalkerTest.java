package com.cobolmodernizer.cobol;

import com.cobolmodernizer.cobol.json.RelationshipJson;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
import org.junit.jupiter.api.Test;

import java.io.File;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class DataFlowWalkerTest {
    private static RelationshipJson find(List<RelationshipJson> rels, String kind, String target) {
        return rels.stream().filter(r -> r.kind().equals(kind) && r.targetQname().equals(target))
                   .findFirst().orElse(null);
    }

    @Test
    void classifiesVsamReaderAndWriterFromSelectAndIoVerbs() {
        File f = new File("src/test/resources/cobol/acctread.cbl");
        CobolIoScanner scanner = new CobolIoScanner(CobolSourceFormatEnum.FIXED);
        List<RelationshipJson> rels = scanner.scanIo(f, "ACCTREAD", "acctread.cbl");

        RelationshipJson reads = find(rels, "READS", "ACCTDAT");
        assertNotNull(reads, "expected READS ACCTDAT");
        assertEquals("VSAM", reads.metadata().get("resourceType"));
        assertEquals("sequential", reads.metadata().get("mode"));

        RelationshipJson writes = find(rels, "WRITES", "OUTFILE");
        assertNotNull(writes, "expected WRITES OUTFILE");
        assertEquals("FILE", writes.metadata().get("resourceType"));
    }
}
