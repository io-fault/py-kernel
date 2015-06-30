"""
C language profile.
"""
from .. import libfields

keyword_list = [
	'asm',
	'auto',
	'break',
	'case',
	'char',
	'const',
	'continue',
	'default',
	'do',
	'double',
	'else',
	'enum',
	'extern',
	'float',
	'for',
	'goto',
	'if',
	'inline',
	'int',
	'long',
	'register',
	'return',
	'short',
	'signed',
	'sizeof',
	'static',
	'struct',
	'switch',
	'typedef',
	'union',
	'unsigned',
	'void',
	'volatile',
	'while',
]

core_list = [
	'printf',
	'fprintf',
	'sprintf',
	'vprintf',
	'vfprintf',
	'vsprintf',

	'scanf',
	'sscanf',
	'fscanf',
	'vscanf',
	'vfscanf',
	'vsscanf',

	'getc',
	'fgetc',
	'getchar',
	'putc',
	'fputc',
	'putchar',

	'getwc',
	'fgetwc',
	'getwchar',
	'putwc',
	'fputwc',
	'putwchar',

	'fopen',
	'freopen',
	'fgetpos',
	'fsetpos',
	'fseek',
	'ftell',
	'rewind',

	'feof',
	'ferror',
	'clearerr',

	'errno',
	'stderr',
	'stdin',
	'stdout',
	'signal',
	'raise',

	'read',
	'write',
	'close',
	'open',
	'flush',

	'malloc',
	'calloc',
	'realloc',
	'free',

	'memcpy',
	'memmove',
	'memset',

	'bzero',
	'bcopy',
	'swab',

	'strlen',
	'strcpy',
	'strcpy',
	'strcat',
	'strcmp',
	'strlwr',
	'strupr',

	'size_t',
	'offset_t',

	'setjmp',
	'longjmp',
	'jmp_buf',
]

exoword_list = [
	'#include',
	'#define',
	'#undef',
	'#if',
	'#ifdef',
	'#ifndef',
	'#elif',
	'#else',
	'#endif',
	'#warning',
	'#error',
	'#line',
	'#pragma',
	'#import',
]

keywords = {y: y for y in map(libfields.String, keyword_list)}
cores = {y: y for y in map(libfields.String, core_list)}
exowords = {y: y for y in map(libfields.String, exoword_list)}

terminators = {y: y for y in map(libfields.Constant, ";")}
separators = {y: y for y in map(libfields.Constant, ",")}
routers = {y: y for y in map(libfields.Constant, (".","-",">"))} # "->"; needs special handling
operators = {y: y for y in map(libfields.Constant, "@!&^*%+=-|\\/<>?~:")}
groupings = {y: y for y in map(libfields.Constant, "()[]{}")}
quotations = {y: y for y in map(libfields.Constant, ("'", '"',))}
