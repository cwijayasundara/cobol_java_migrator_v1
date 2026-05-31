package com.cobolmodernizer.cobol;

import com.cobolmodernizer.cobol.json.EntityJson;
import com.cobolmodernizer.cobol.json.FileResultJson;
import com.cobolmodernizer.cobol.json.RelationshipJson;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Adds isExternal stub entities for CALL/COPY targets not defined anywhere in the batch. */
public final class ExternalResolver {
    private ExternalResolver() {}

    public static List<FileResultJson> addExternalStubs(List<FileResultJson> files) {
        Set<String> defined = new HashSet<>();
        for (FileResultJson f : files)
            for (EntityJson e : f.entities()) defined.add(e.qualifiedName());

        List<FileResultJson> out = new ArrayList<>();
        for (FileResultJson f : files) {
            List<EntityJson> entities = new ArrayList<>(f.entities());
            Set<String> localQn = new HashSet<>();
            for (EntityJson e : entities) localQn.add(e.qualifiedName());
            for (RelationshipJson r : f.relationships()) {
                boolean external = r.kind().equals("CALLS") || r.kind().equals("IMPORTS");
                if (external && !defined.contains(r.targetQname()) && localQn.add(r.targetQname())) {
                    String kind = r.kind().equals("IMPORTS") ? "Copybook" : "Program";
                    entities.add(new EntityJson(kind, r.targetQname(), r.targetQname(), "", 0, 0, true));
                }
            }
            out.add(new FileResultJson(f.filePath(), f.parseStatus(), f.error(),
                    entities, f.relationships()));
        }
        return out;
    }
}
