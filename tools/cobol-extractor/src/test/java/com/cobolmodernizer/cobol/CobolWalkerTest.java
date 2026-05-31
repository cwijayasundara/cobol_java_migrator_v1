package com.cobolmodernizer.cobol;

import com.cobolmodernizer.cobol.json.FileResultJson;
import org.junit.jupiter.api.Test;

import java.io.File;

import static org.junit.jupiter.api.Assertions.*;

class CobolWalkerTest {
    @Test
    void extractsProgramParagraphsAndPerform() {
        File f = new File("src/test/resources/cobol/hello.cbl");
        FileResultJson r = new CobolWalker("FIXED", java.util.List.of()).walk(f, "hello.cbl");

        assertEquals("ok", r.parseStatus());
        assertTrue(r.entities().stream().anyMatch(e ->
            e.kind().equals("Program") && e.qualifiedName().equals("HELLO")));
        assertTrue(r.entities().stream().anyMatch(e ->
            e.kind().equals("Paragraph") && e.qualifiedName().equals("HELLO.MAIN-PARA")));
        assertTrue(r.relationships().stream().anyMatch(rel ->
            rel.kind().equals("CALLS")
            && rel.targetQname().equals("HELLO.SUB-PARA")
            && "perform".equals(rel.metadata().get("type"))));
        assertTrue(r.relationships().stream().anyMatch(rel ->
            rel.kind().equals("CONTAINS")
            && rel.sourceQname().equals("HELLO")
            && rel.targetQname().equals("HELLO.MAIN-PARA")));
    }

    @Test
    void malformedFileReportsError() {
        File f = new File("src/test/resources/cobol/broken.cbl");
        FileResultJson r = new CobolWalker("FIXED", java.util.List.of()).walk(f, "broken.cbl");
        assertEquals("error", r.parseStatus());
        assertNotNull(r.error());
        assertTrue(r.entities().isEmpty());
    }
}
