package com.cobolmodernizer.cobol;

import com.cobolmodernizer.cobol.json.FileResultJson;
import org.junit.jupiter.api.Test;

import java.io.File;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class SectionTest {
    private FileResultJson walk() {
        return new CobolWalker("FIXED", List.of())
            .walk(new File("src/test/resources/cobol/withsec.cbl"), "withsec.cbl");
    }

    @Test
    void emitsSectionEntitiesContainedByProgram() {
        FileResultJson r = walk();
        assertEquals("ok", r.parseStatus());
        assertTrue(r.entities().stream().anyMatch(e ->
            e.kind().equals("Section") && e.qualifiedName().equals("WITHSEC.A-SECTION")));
        assertTrue(r.relationships().stream().anyMatch(rel ->
            rel.kind().equals("CONTAINS") && rel.sourceQname().equals("WITHSEC")
            && rel.targetQname().equals("WITHSEC.A-SECTION")));
    }

    @Test
    void paragraphsAreContainedByTheirSection() {
        FileResultJson r = walk();
        assertTrue(r.entities().stream().anyMatch(e ->
            e.kind().equals("Paragraph") && e.qualifiedName().equals("WITHSEC.A-PARA")));
        assertTrue(r.relationships().stream().anyMatch(rel ->
            rel.kind().equals("CONTAINS")
            && rel.sourceQname().equals("WITHSEC.A-SECTION")
            && rel.targetQname().equals("WITHSEC.A-PARA")));
    }

    @Test
    void allSectionParagraphsReparented() {
        FileResultJson r = walk();
        assertTrue(r.relationships().stream().anyMatch(rel ->
            rel.kind().equals("CONTAINS") && rel.sourceQname().equals("WITHSEC.A-SECTION")
            && rel.targetQname().equals("WITHSEC.B-PARA")));
        assertTrue(r.relationships().stream().anyMatch(rel ->
            rel.kind().equals("CONTAINS") && rel.sourceQname().equals("WITHSEC.C-SECTION")
            && rel.targetQname().equals("WITHSEC.C-PARA")));
    }
}
