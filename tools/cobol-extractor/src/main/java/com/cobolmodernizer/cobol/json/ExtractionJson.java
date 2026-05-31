package com.cobolmodernizer.cobol.json;

import java.util.List;

public record ExtractionJson(int schemaVersion, List<FileResultJson> files) {}
