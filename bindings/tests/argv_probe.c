/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <string.h>
#include "../native/qemu-cli.h"

QEMU_CLI_EXPORT int dll_main(int argc, char **argv)
{
    static const char *expected[] = {
        "", "two words", "\"quoted\"", "back\\slash", "--",
        "caf\xc3\xa9 \xf0\x9f\x90\xa7"
    };
    if (argc != 7 || !argv[0] || !argv[0][0] || argv[argc] != NULL) {
        return 98;
    }
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], expected[i - 1])) {
            return 99;
        }
    }
    /* The native CLI is allowed to modify argument storage. */
    argv[2][0] = 'T';
    argv[2] = argv[1];
    return 37;
}

QEMU_CLI_EXPORT int main(int argc, char **argv)
{
    return dll_main(argc, argv);
}
