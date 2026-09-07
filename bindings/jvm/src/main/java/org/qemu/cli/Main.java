package org.qemu.cli;

import org.qemu.Qemu;

public final class Main {
    private Main() {}

    public static void main(String[] arguments) {
        try {
            System.exit(Qemu.run(arguments));
        } catch (Exception | UnsatisfiedLinkError error) {
            System.err.println("qemu: " + error.getMessage());
            System.exit(1);
        }
    }
}
