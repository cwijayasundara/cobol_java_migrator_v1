package com.cobolmodernizer.cobol;

import com.cobolmodernizer.cobol.json.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertTrue;

class JsonShapeTest {
    @Test
    void serializesContractShape() throws Exception {
        EntityJson e = new EntityJson("Program", "PAY", "PAY", "src/PAY.cbl", 1, 9, false);
        RelationshipJson r = new RelationshipJson("PAY", "PAY.MAIN", "CONTAINS", "src/PAY.cbl", 3, java.util.Map.of());
        FileResultJson fr = new FileResultJson("src/PAY.cbl", "ok", null, List.of(e), List.of(r));
        ExtractionJson root = new ExtractionJson(2, List.of(fr));

        String json = new ObjectMapper().writeValueAsString(root);
        assertTrue(json.contains("\"schemaVersion\":2"));
        assertTrue(json.contains("\"qualifiedName\":\"PAY\""));
        assertTrue(json.contains("\"isExternal\":false"));
        assertTrue(json.contains("\"kind\":\"CONTAINS\""));
    }
}
