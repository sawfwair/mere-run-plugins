#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef PLUGIN_MODULE
#error PLUGIN_MODULE must name a reviewed plugin module
#endif

int main(int argc, char **argv) {
    char executable[PATH_MAX], resolved[PATH_MAX], interpreter[PATH_MAX];
    uint32_t capacity = sizeof(executable);
    if (_NSGetExecutablePath(executable, &capacity) || !realpath(executable, resolved)) {
        perror("Cannot locate plugin bundle");
        return 70;
    }
    for (int level = 0; level < 2; level++) {
        char *separator = strrchr(resolved, '/');
        if (!separator) return 70;
        *separator = '\0';
    }
    if (snprintf(interpreter, sizeof(interpreter), "%s/MacOS/MereWorkflowTools", resolved)
        >= (int)sizeof(interpreter)) return 70;
    char **args = calloc((size_t)argc + 2, sizeof(char *));
    if (!args) return 70;
    args[0] = interpreter;
    args[1] = PLUGIN_MODULE;
    for (int index = 1; index < argc; index++) args[index + 1] = argv[index];
    execv(interpreter, args);
    perror("Cannot start bundled Python");
    free(args);
    return 70;
}
