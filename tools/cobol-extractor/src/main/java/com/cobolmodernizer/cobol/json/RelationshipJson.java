package com.cobolmodernizer.cobol.json;

import java.util.Map;

public record RelationshipJson(
    String sourceQname, String targetQname, String kind,
    String filePath, Integer line, Map<String, Object> metadata) {}
