/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef QEMU_CLI_H
#define QEMU_CLI_H

#ifdef _WIN32
#define QEMU_CLI_EXPORT __declspec(dllexport)
#else
#define QEMU_CLI_EXPORT __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif
/* One call per process. Like main(), this can call exit() and owns signals. */
QEMU_CLI_EXPORT int dll_main(int argc, char **argv);
QEMU_CLI_EXPORT int main(int argc, char **argv);
#ifdef __cplusplus
}
#endif
#endif
