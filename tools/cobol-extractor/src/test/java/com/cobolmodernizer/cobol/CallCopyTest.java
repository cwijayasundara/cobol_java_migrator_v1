package com.cobolmodernizer.cobol;

import com.cobolmodernizer.cobol.json.FileResultJson;
import org.junit.jupiter.api.Test;

import java.io.File;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class CallCopyTest {
    @Test
    void callEdgesToProgram() {
        FileResultJson r = new CobolWalker("FIXED", List.of())
            .walk(new File("src/test/resources/cobol/caller.cbl"), "caller.cbl");
        assertEquals("ok", r.parseStatus());
        assertTrue(r.relationships().stream().anyMatch(rel ->
            rel.kind().equals("CALLS") && rel.sourceQname().equals("CALLER")
            && rel.targetQname().equals("CALLEE") && "call".equals(rel.metadata().get("type"))));
    }

    @Test
    void copyEdgeToCopybook() {
        FileResultJson r = new CobolWalker("FIXED", List.of(
            new File("src/test/resources/cobol/copybooks")))
            .walk(new File("src/test/resources/cobol/withcopy.cbl"), "withcopy.cbl");
        assertEquals("ok", r.parseStatus());
        assertTrue(r.relationships().stream().anyMatch(rel ->
            rel.kind().equals("IMPORTS") && rel.sourceQname().equals("WITHCOPY")
            && rel.targetQname().equals("CUSTREC")));
        assertTrue(r.entities().stream().anyMatch(e ->
            e.kind().equals("Copybook") && e.qualifiedName().equals("CUSTREC")));
    }

    @Test
    void commentedCopyIsSkipped() {
        FileResultJson r = new CobolWalker("FIXED", List.of(
            new File("src/test/resources/cobol/copybooks")))
            .walk(new File("src/test/resources/cobol/copycomment.cbl"), "copycomment.cbl");
        assertEquals("ok", r.parseStatus());
        assertTrue(r.entities().stream().anyMatch(e -> e.qualifiedName().equals("CUSTREC")));
        assertFalse(r.entities().stream().anyMatch(e -> e.qualifiedName().equals("SHOULDSKIP")));
    }

    @Test
    void unresolvedCallProducesExternalStub() {
        FileResultJson r = new CobolWalker("FIXED", List.of())
            .walk(new File("src/test/resources/cobol/caller.cbl"), "caller.cbl");
        List<FileResultJson> resolved = ExternalResolver.addExternalStubs(List.of(r));
        assertTrue(resolved.get(0).entities().stream().anyMatch(e ->
            e.qualifiedName().equals("MISSINGSUB") && e.isExternal()));
    }
}
