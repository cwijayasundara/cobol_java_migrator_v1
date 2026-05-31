package com.cobolmodernizer.cobol;

import com.cobolmodernizer.cobol.json.ExtractionJson;
import com.cobolmodernizer.cobol.json.FileResultJson;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
import picocli.CommandLine;
import picocli.CommandLine.Option;

import java.io.File;
import java.io.PrintStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.stream.Collectors;

@CommandLine.Command(name = "cobol-extractor", mixinStandardHelpOptions = true)
public class ExtractorMain implements Callable<Integer> {
    @Option(names = "--source-dir", required = true) String sourceDir;
    @Option(names = "--copybook-dir") List<String> copybookDirs = new ArrayList<>();
    @Option(names = "--format",
            description = "COBOL source format: FIXED, VARIABLE, or TANDEM (default FIXED).")
    String format = "FIXED";
    @Option(names = "--extensions") String extensions = ".cbl,.cob,.cobol";
    @Option(names = "--out") String out = "-";

    static final int SCHEMA_VERSION = 2;
    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Override
    public Integer call() throws Exception {
        if (!isValidFormat(format)) {
            System.err.println("Invalid --format: " + format
                    + ". Valid values: FIXED, VARIABLE, TANDEM");
            return 2;
        }
        // Keep ProLeap's stdout chatter off our JSON: redirect stdout to stderr
        // during parsing, restore it only to emit the final JSON.
        PrintStream realOut = System.out;
        String json;
        try {
            System.setOut(System.err);
            json = produce(sourceDir, copybookDirs, format, extensions);
        } finally {
            System.setOut(realOut);
        }
        if ("-".equals(out)) {
            realOut.println(json);
        } else {
            Files.writeString(Path.of(out), json);
        }
        return 0;
    }

    /** Test seam: parse args, run, return the JSON string. The --out option is ignored
     *  (the JSON is returned directly rather than written/printed). */
    static String run(String[] args) throws Exception {
        ExtractorMain m = new ExtractorMain();
        new CommandLine(m).parseArgs(args);
        return produce(m.sourceDir, m.copybookDirs, m.format, m.extensions);
    }

    private static String produce(String sourceDir, List<String> copybookDirs,
                                  String format, String extensions) throws Exception {
        Set<String> exts = Arrays.stream(extensions.split(","))
            .map(String::trim).map(String::toLowerCase).collect(Collectors.toSet());
        List<File> copyDirs = copybookDirs.stream().map(File::new).toList();
        Path root = Path.of(sourceDir);

        CobolWalker walker = new CobolWalker(format, copyDirs);
        List<FileResultJson> files = new ArrayList<>();
        try (var stream = Files.walk(root)) {
            for (Path p : stream.filter(Files::isRegularFile).sorted().toList()) {
                String name = p.getFileName().toString().toLowerCase();
                int dot = name.lastIndexOf('.');
                if (dot < 0 || !exts.contains(name.substring(dot))) continue;
                String rel = root.relativize(p).toString();
                files.add(walker.walk(p.toFile(), rel));
            }
        }
        files = ExternalResolver.addExternalStubs(files);
        return MAPPER.writeValueAsString(new ExtractionJson(SCHEMA_VERSION, files));
    }

    private static boolean isValidFormat(String f) {
        try {
            CobolSourceFormatEnum.valueOf(f);
            return true;
        } catch (IllegalArgumentException e) {
            return false;
        }
    }

    public static void main(String[] args) {
        try {
            System.exit(new CommandLine(new ExtractorMain()).execute(args));
        } catch (Exception e) {
            System.err.println("FATAL: " + e);
            System.exit(1);
        }
    }
}
