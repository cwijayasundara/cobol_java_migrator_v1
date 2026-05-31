package com.cobolmodernizer.cobol;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class ExtractorMainTest {
    @Test
    void runEmitsContractJson() throws Exception {
        String json = ExtractorMain.run(new String[]{
            "--source-dir", "src/test/resources/cobol",
            "--format", "FIXED",
            "--copybook-dir", "src/test/resources/cobol/copybooks",
            "--out", "-",
        });
        JsonNode root = new ObjectMapper().readTree(json);
        assertEquals(2, root.get("schemaVersion").asInt());
        assertTrue(root.get("files").isArray());
        assertTrue(root.get("files").size() >= 4);  // hello, caller, callee, withcopy, withsec, copycomment, broken
    }
}
