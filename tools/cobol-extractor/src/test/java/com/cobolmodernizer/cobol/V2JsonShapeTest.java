package com.cobolmodernizer.cobol;

import com.cobolmodernizer.cobol.json.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertTrue;

class V2JsonShapeTest {
    @Test
    void serializesV2ContractWithDataItemsAndIoEdges() throws Exception {
        EntityJson prog = new EntityJson("Program", "CBACT01C", "CBACT01C",
                "app/cbl/CBACT01C.cbl", 1, 200, false);
        DataItemJson di = new DataItemJson("DataItem", "CBACT01C.WS-ACCT-ID", "WS-ACCT-ID",
                "app/cbl/CBACT01C.cbl", 40, 40, false,
                5, "9(11)", "DISPLAY", null, 0, "CBACT01C.WS-ACCT-REC");
        RelationshipJson reads = new RelationshipJson("CBACT01C", "ACCTDAT", "READS",
                "app/cbl/CBACT01C.cbl", 120,
                Map.of("resource", "ACCTDAT", "resourceType", "VSAM", "mode", "sequential"));
        FileResultJson fr = new FileResultJson("app/cbl/CBACT01C.cbl", "ok", null,
                List.of(prog), List.of(di), List.of(reads));
        ExtractionJson root = new ExtractionJson(2, List.of(fr));

        String json = new ObjectMapper().writeValueAsString(root);
        assertTrue(json.contains("\"schemaVersion\":2"), json);
        assertTrue(json.contains("\"dataItems\""), json);
        assertTrue(json.contains("\"kind\":\"DataItem\""), json);
        assertTrue(json.contains("\"picture\":\"9(11)\""), json);
        assertTrue(json.contains("\"parentQname\":\"CBACT01C.WS-ACCT-REC\""), json);
        assertTrue(json.contains("\"kind\":\"READS\""), json);
        assertTrue(json.contains("\"resourceType\":\"VSAM\""), json);
    }
}
