package com.cobolmodernizer.cobol.json;

import java.util.List;

public record FileResultJson(
    String filePath, String parseStatus, String error,
    List<EntityJson> entities,
    List<DataItemJson> dataItems,
    List<RelationshipJson> relationships) {}
