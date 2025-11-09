from function_category import FunctionCategory


_HEADER_CATALOG = {
    # --- C 标准库 ---
    'stdio.h': {
        'category': FunctionCategory.STANDARD_LIBRARY,
        'description': 'Standard I/O library',
        'functions': [
            'printf', 'fprintf', 'sprintf', 'snprintf', 'vprintf', 'vfprintf', 'vsprintf', 'vsnprintf',
            'scanf', 'fscanf', 'sscanf',
            'getchar', 'putchar', 'puts', 'fgets', 'fputs', 'fgetc', 'fputc', 'ungetc',
            'fread', 'fwrite',
            'fopen', 'freopen', 'fclose', 'fflush',
            'fseek', 'ftell', 'rewind', 'fgetpos', 'fsetpos',
            'perror', 'remove', 'rename', 'tmpfile', 'tmpnam', 'setbuf', 'setvbuf'
        ]
    },
    'stdlib.h': {
        'category': FunctionCategory.STANDARD_LIBRARY,
        'description': 'General utilities library',
        'functions': [
            'malloc', 'calloc', 'realloc', 'free', 'aligned_alloc',
            'abort', 'exit', 'quick_exit', '_Exit', 'atexit',
            'atof', 'atoi', 'atol', 'atoll',
            'strtod', 'strtof', 'strtold', 'strtol', 'strtoll', 'strtoul', 'strtoull',
            'bsearch', 'qsort',
            'rand', 'srand',
            'abs', 'labs', 'llabs', 'div', 'ldiv', 'lldiv',
            'mblen', 'mbtowc', 'wctomb', 'mbstowcs', 'wcstombs',
            'getenv', 'system'
        ]
    },
    'string.h': {
        'category': FunctionCategory.STANDARD_LIBRARY,
        'description': 'String handling',
        'functions': [
            'memcpy', 'memmove', 'memset', 'memcmp', 'memchr',
            'strcpy', 'strncpy', 'strcat', 'strncat', 'strlen', 'strcmp', 'strncmp',
            'strchr', 'strrchr', 'strstr', 'strspn', 'strcspn', 'strpbrk', 'strerror'
        ]
    },
    'ctype.h': {
        'category': FunctionCategory.STANDARD_LIBRARY,
        'description': 'Character classification and conversion',
        'functions': [
            'isalnum', 'isalpha', 'iscntrl', 'isdigit', 'isgraph', 'islower', 'isprint', 'ispunct', 'isspace', 'isupper', 'isxdigit',
            'tolower', 'toupper'
        ]
    },
    'math.h': {
        'category': FunctionCategory.STANDARD_LIBRARY,
        'description': 'Mathematics library',
        'functions': [
            'sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'atan2',
            'sinh', 'cosh', 'tanh',
            'exp', 'frexp', 'ldexp', 'log', 'log10', 'modf', 'pow', 'sqrt', 'fmod', 'trunc', 'round', 'lround', 'llround', 'ceil', 'floor', 'fabs'
        ]
    },
    'time.h': {
        'category': FunctionCategory.STANDARD_LIBRARY,
        'description': 'Time utilities',
        'functions': [
            'time', 'difftime', 'mktime', 'gmtime', 'localtime', 'strftime', 'clock', 'asctime', 'ctime', 'timespec_get'
        ]
    },
    'locale.h': {
        'category': FunctionCategory.STANDARD_LIBRARY,
        'description': 'Localization utilities',
        'functions': ['setlocale', 'localeconv']
    },
    'setjmp.h': {
        'category': FunctionCategory.STANDARD_LIBRARY,
        'description': 'Nonlocal jumps',
        'functions': ['setjmp', 'longjmp']
    },
    'stdarg.h': {
        'category': FunctionCategory.STANDARD_LIBRARY,
        'description': 'Variable arguments',
        'functions': ['va_start', 'va_arg', 'va_end', 'va_copy']
    },
    'wchar.h': {
        'category': FunctionCategory.STANDARD_LIBRARY,
        'description': 'Wide-character utilities',
        'functions': [
            'fgetwc', 'fgetws', 'fputwc', 'fputws', 'fwide', 'getwc', 'getwchar', 'putwc', 'putwchar', 'ungetwc',
            'wcstod', 'wcstof', 'wcstold',
            'wcscpy', 'wcsncpy', 'wcscat', 'wcsncat', 'wcscmp', 'wcsncmp', 'wcschr', 'wcsrchr', 'wcslen',
            'wmemcpy', 'wmemmove', 'wmemset', 'wmemchr'
        ]
    },
    'wctype.h': {
        'category': FunctionCategory.STANDARD_LIBRARY,
        'description': 'Wide-character classification',
        'functions': [
            'iswalnum', 'iswalpha', 'iswcntrl', 'iswdigit', 'iswgraph', 'iswlower', 'iswprint', 'iswpunct', 'iswspace', 'iswupper', 'iswxdigit',
            'towlower', 'towupper'
        ]
    },
    'complex.h': {
        'category': FunctionCategory.STANDARD_LIBRARY,
        'description': 'Complex math',
        'functions': [
            'cabs', 'carg', 'cexp', 'clog', 'cpow', 'csqrt',
            'cacos', 'casin', 'catan', 'ccos', 'csin', 'ctan',
            'cacosh', 'casinh', 'catanh', 'ccosh', 'csinh', 'ctanh'
        ]
    },
    'fenv.h': {
        'category': FunctionCategory.STANDARD_LIBRARY,
        'description': 'Floating-point environment',
        'functions': [
            'fegetenv', 'fesetenv', 'feclearexcept', 'feraiseexcept', 'fegetexceptflag', 'fesetexceptflag', 'fetestexcept', 'fegetround', 'fesetround', 'feholdexcept', 'feupdateenv'
        ]
    },

    # --- POSIX / 系统调用 ---
    'unistd.h': {
        'category': FunctionCategory.SYSTEM_CALL,
        'description': 'POSIX operating system API',
        'functions': [
            'read', 'write', 'close', 'lseek', 'pipe', 'dup', 'dup2', 'fork', 'execve', 'execvp', 'sleep', 'usleep',
            'chdir', 'getcwd', 'getpid', 'getppid', 'access', 'getopt'
        ]
    },
    'fcntl.h': {
        'category': FunctionCategory.SYSTEM_CALL,
        'description': 'File control options',
        'functions': ['open', 'creat', 'fcntl']
    },
    'sys/stat.h': {
        'category': FunctionCategory.SYSTEM_CALL,
        'description': 'File status',
        'functions': ['stat', 'fstat', 'lstat', 'chmod', 'mkdir', 'mkfifo', 'umask']
    },
    'sys/socket.h': {
        'category': FunctionCategory.SYSTEM_CALL,
        'description': 'Berkeley sockets API',
        'functions': ['socket', 'bind', 'listen', 'accept', 'connect', 'send', 'recv', 'sendto', 'recvfrom', 'shutdown', 'getsockopt', 'setsockopt']
    },
    'netinet/in.h': {
        'category': FunctionCategory.SYSTEM_CALL,
        'description': 'Internet address family',
        'functions': ['htons', 'htonl', 'ntohs', 'ntohl']
    },
    'arpa/inet.h': {
        'category': FunctionCategory.SYSTEM_CALL,
        'description': 'Internet operations',
        'functions': ['inet_addr', 'inet_aton', 'inet_ntoa', 'inet_pton', 'inet_ntop']
    },
    'dlfcn.h': {
        'category': FunctionCategory.EXTERNAL_LIBRARY,
        'description': 'Dynamic linking',
        'functions': ['dlopen', 'dlsym', 'dlclose', 'dlerror']
    },
    'pthread.h': {
        'category': FunctionCategory.EXTERNAL_LIBRARY,
        'description': 'POSIX threads',
        'functions': [
            'pthread_create', 'pthread_join', 'pthread_detach',
            'pthread_mutex_init', 'pthread_mutex_lock', 'pthread_mutex_unlock', 'pthread_mutex_destroy',
            'pthread_cond_init', 'pthread_cond_wait', 'pthread_cond_signal', 'pthread_cond_broadcast', 'pthread_cond_destroy',
            'pthread_rwlock_init', 'pthread_rwlock_rdlock', 'pthread_rwlock_wrlock', 'pthread_rwlock_unlock', 'pthread_rwlock_destroy'
        ]
    },
    'sys/mman.h': {
        'category': FunctionCategory.SYSTEM_CALL,
        'description': 'Memory management',
        'functions': ['mmap', 'munmap', 'mprotect', 'msync']
    },
    'poll.h': {
        'category': FunctionCategory.SYSTEM_CALL,
        'description': 'I/O multiplexing',
        'functions': ['poll']
    },
    'sys/select.h': {
        'category': FunctionCategory.SYSTEM_CALL,
        'description': 'I/O multiplexing',
        'functions': ['select']
    },
    'sys/epoll.h': {
        'category': FunctionCategory.SYSTEM_CALL,
        'description': 'Linux epoll',
        'functions': ['epoll_create', 'epoll_ctl', 'epoll_wait']
    },
    'dirent.h': {
        'category': FunctionCategory.SYSTEM_CALL,
        'description': 'Directory entries',
        'functions': ['opendir', 'readdir', 'closedir']
    },
    'regex.h': {
        'category': FunctionCategory.EXTERNAL_LIBRARY,
        'description': 'Regular expressions (POSIX)',
        'functions': ['regcomp', 'regexec', 'regfree', 'regerror']
    },
    'signal.h': {
        'category': FunctionCategory.SYSTEM_CALL,
        'description': 'Signals',
        'functions': ['signal', 'raise', 'sigaction', 'kill']
    },
    'termios.h': {
        'category': FunctionCategory.SYSTEM_CALL,
        'description': 'Terminal I/O',
        'functions': ['tcgetattr', 'tcsetattr']
    },
}


def _build_known_functions():
    mapping = {}
    for header, meta in _HEADER_CATALOG.items():
        category = meta['category']
        description = meta.get('description', '')
        for fname in meta.get('functions', []):
            mapping[fname] = {
                'category': category,
                'header': header,
                'description': description
            }
    # 额外的常见第三方或项目特定函数示例
    mapping.setdefault('scrcpy', {
        'category': FunctionCategory.EXTERNAL_LIBRARY,
        'header': 'scrcpy.h',
        'description': 'Screen mirroring and control'
    })
    return mapping


KNOWN_FUNCTIONS = _build_known_functions()


