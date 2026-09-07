package org.qemu;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Locale;

/** One-shot JNI access to QEMU's native CLI. QEMU may exit the JVM. */
public final class Qemu {
    private static boolean called;

    private Qemu() {}

    public static String hostTarget() {
        String os = System.getProperty("os.name").toLowerCase(Locale.ROOT);
        String system = os.startsWith("windows") ? "windows"
                : os.startsWith("mac") ? "macos" : os.equals("linux") ? "linux" : null;
        String arch = switch (System.getProperty("os.arch").toLowerCase(Locale.ROOT)) {
            case "amd64", "x86_64" -> "x86_64";
            case "arm64", "aarch64" -> "aarch64";
            default -> null;
        };
        if (system == null || arch == null) {
            throw new IllegalStateException("Unsupported QEMU host: " + os + "/" + System.getProperty("os.arch"));
        }
        return system + "-" + arch;
    }

    private static String hash(byte[] data) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(data));
        } catch (NoSuchAlgorithmException impossible) {
            throw new AssertionError(impossible);
        }
    }

    private static byte[] resource(String name) throws IOException {
        try (InputStream input = Qemu.class.getResourceAsStream("/native/" + name)) {
            if (input == null) throw new IOException("Missing native resource: " + name);
            return input.readAllBytes();
        }
    }

    private static Path bundle(String target) throws IOException {
        String override = System.getenv("QEMU_BUNDLE_DIR");
        if (override != null && !override.isEmpty()) return Path.of(override).toAbsolutePath();
        byte[] manifest = resource(target + "/files.list");
        String cache = System.getenv("QEMU_CACHE_DIR");
        Path base = cache == null || cache.isEmpty()
                ? Path.of(System.getProperty("user.home"), ".cache", "qemu-cli") : Path.of(cache);
        Path root = base.toAbsolutePath().resolve(target).resolve(hash(manifest));
        Files.createDirectories(root);
        for (String line : new String(manifest, StandardCharsets.UTF_8).split("\n")) {
            if (line.isEmpty()) continue;
            String[] fields = line.split("  ", 2);
            if (fields.length != 2 || !fields[0].matches("[a-f0-9]{64}")) {
                throw new IOException("Invalid native manifest");
            }
            Path output = root.resolve(fields[1]).normalize();
            if (!output.startsWith(root) || fields[1].contains("\\")) {
                throw new IOException("Unsafe native resource: " + fields[1]);
            }
            if (Files.isRegularFile(output) && hash(Files.readAllBytes(output)).equals(fields[0])) continue;
            byte[] data = resource(target + "/" + fields[1]);
            if (!hash(data).equals(fields[0])) throw new IOException("Corrupt native resource: " + fields[1]);
            Files.createDirectories(output.getParent());
            Path temporary = Files.createTempFile(output.getParent(), ".extract-", ".tmp");
            try {
                Files.write(temporary, data);
                Files.move(temporary, output, StandardCopyOption.REPLACE_EXISTING);
            } finally {
                Files.deleteIfExists(temporary);
            }
        }
        return root.resolve("qemu");
    }

    public static synchronized int run(String... arguments) throws IOException {
        if (called) throw new IllegalStateException("QEMU dll_main may only be called once per process");
        String target = hostTarget();
        String guest = System.getenv("QEMU_GUEST");
        if (guest == null || guest.isEmpty()) guest = target.substring(target.indexOf('-') + 1);
        if (!guest.matches("[a-z0-9_-]+")) throw new IllegalArgumentException("Invalid QEMU_GUEST");
        Path bin = bundle(target).resolve("bin");
        String suffix = target.startsWith("windows-") ? ".dll" : target.startsWith("macos-") ? ".dylib" : ".so";
        Path library = bin.resolve("libqemu-system-" + guest + suffix);
        if (!Files.isRegularFile(library)) throw new IOException("Guest is not bundled: " + guest);
        byte[][] argv = new byte[arguments.length + 1][];
        argv[0] = library.toString().getBytes(StandardCharsets.UTF_8);
        for (int i = 0; i < arguments.length; i++) {
            if (arguments[i].indexOf('\0') >= 0) throw new IllegalArgumentException("QEMU arguments cannot contain NUL");
            argv[i + 1] = arguments[i].getBytes(StandardCharsets.UTF_8);
        }
        System.load(bin.resolve("libqemu_jni" + suffix).toString());
        called = true;
        return runNative(library.toString(), argv);
    }

    private static native int runNative(String library, byte[][] arguments);
}
