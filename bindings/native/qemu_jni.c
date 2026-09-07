/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <jni.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#endif

static void fail(JNIEnv *env, const char *message)
{
    jclass cls = (*env)->FindClass(env, "java/lang/IllegalStateException");
    if (cls) {
        (*env)->ThrowNew(env, cls, message);
    }
}

JNIEXPORT jint JNICALL Java_org_qemu_Qemu_runNative(
    JNIEnv *env, jclass cls, jstring path, jobjectArray arguments)
{
    int (*entry)(int, char **);
    jsize argc = (*env)->GetArrayLength(env, arguments);
    char **argv;
    char **storage;
    int result = -1;
    (void)cls;

    if (argc == INT_MAX) {
        fail(env, "Too many QEMU arguments");
        return -1;
    }
#ifdef _WIN32
    const jchar *chars = (*env)->GetStringChars(env, path, NULL);
    jsize length = (*env)->GetStringLength(env, path);
    wchar_t *wide = calloc((size_t)length + 1, sizeof(wchar_t));
    HMODULE library;
    if (!chars || !wide) {
        if (chars) (*env)->ReleaseStringChars(env, path, chars);
        free(wide);
        fail(env, "Cannot allocate QEMU library path");
        return -1;
    }
    memcpy(wide, chars, (size_t)length * sizeof(wchar_t));
    (*env)->ReleaseStringChars(env, path, chars);
    library = LoadLibraryExW(wide, NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR |
                                          LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    free(wide);
    entry = library ? (int (*)(int, char **))GetProcAddress(library, "dll_main") : NULL;
#else
    /* Java supplies the library path as UTF-8 in argv[0], not JNI modified UTF-8. */
    jbyteArray first = (*env)->GetObjectArrayElement(env, arguments, 0);
    jsize length = (*env)->GetArrayLength(env, first);
    char *name = calloc((size_t)length + 1, 1);
    void *library;
    if (!name) {
        fail(env, "Cannot allocate QEMU library path");
        return -1;
    }
    (*env)->GetByteArrayRegion(env, first, 0, length, (jbyte *)name);
    (*env)->DeleteLocalRef(env, first);
    library = dlopen(name, RTLD_NOW | RTLD_LOCAL);
    free(name);
    entry = library ? (int (*)(int, char **))dlsym(library, "dll_main") : NULL;
    (void)path;
#endif
    if (!entry) {
#ifdef _WIN32
        fail(env, "Cannot load QEMU DLL or find dll_main");
#else
        fail(env, dlerror());
#endif
        return -1;
    }
    /* QEMU can retain pointers into argv, so keep it alive for the whole call. */
    argv = calloc((size_t)argc + 1, sizeof(*argv));
    storage = calloc((size_t)argc + 1, sizeof(*storage));
    if (!argv || !storage) {
        free(argv);
        free(storage);
        fail(env, "Cannot allocate QEMU argv");
        return -1;
    }
    for (jsize i = 0; i < argc; i++) {
        jbyteArray arg = (*env)->GetObjectArrayElement(env, arguments, i);
        jsize size = (*env)->GetArrayLength(env, arg);
        argv[i] = storage[i] = calloc((size_t)size + 1, 1);
        if (!argv[i]) {
            (*env)->DeleteLocalRef(env, arg);
            fail(env, "Cannot allocate QEMU argument");
            goto out;
        }
        (*env)->GetByteArrayRegion(env, arg, 0, size, (jbyte *)argv[i]);
        (*env)->DeleteLocalRef(env, arg);
        if ((*env)->ExceptionCheck(env)) goto out;
    }
    result = entry(argc, argv);
out:
    /* main() may reorder or replace argv pointers; free the original storage. */
    for (jsize i = 0; i < argc; i++) free(storage[i]);
    free(storage);
    free(argv);
    /* Do not dlclose: QEMU registers process-global callbacks and threads. */
    return result;
}
