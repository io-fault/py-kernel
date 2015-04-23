#if 0
csource = """
#endif
/*
 * kernel.py.c - kernel interfaces for process invocation and exit signalling
 */
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/types.h>
#include <sys/stat.h>

#include <spawn.h>

#include <sys/event.h>
typedef struct kevent kevent_t; /* kernel event description */
#define KQ_FILTERS() \
	FILTER(EVFILT_USER) \
	FILTER(EVFILT_PROC) \
	FILTER(EVFILT_SIGNAL) \
	FILTER(EVFILT_VNODE) \
	FILTER(EVFILT_TIMER)

#define KQ_FLAGS() \
	FLAG(EV_ADD) \
	FLAG(EV_ENABLE) \
	FLAG(EV_DISABLE) \
	FLAG(EV_DELETE) \
	FLAG(EV_RECEIPT) \
	FLAG(EV_ONESHOT) \
	FLAG(EV_CLEAR) \
	FLAG(EV_EOF) \
	FLAG(EV_ERROR)

/*
 * Signals that kernel.Interface will listen for automatically.
 *
 * SIGINT is handled fork.library.control() with signal.signal.
 * SIGUSR2 is *explicitly* used to trigger interjections.
 *
 * *All* Context instances will receive signals.
 */
#define KQ_SIGNALS() \
	SIGNAME(SIGTERM) \
	SIGNAME(SIGHUP) \
	SIGNAME(SIGCONT) \
	SIGNAME(SIGINFO) \
	SIGNAME(SIGWINCH) \
	SIGNAME(SIGUSR1)

/*
 *	SIGNAME(SIGUSR2)
 *
 *	SIGUSR2 is used to interrupt the main thread. This is used
 *	to allow system.interject() to operate.
 */

#ifndef HAVE_STDINT_H
/* relying on Python's checks */
#include <stdint.h>
#endif

#ifndef CONFIG_STATIC_KEVENTS
#define CONFIG_STATIC_KEVENTS 16
#elif CONFIG_STATIC_KEVENTS < 8
#undef CONFIG_STATIC_KEVENTS
#define CONFIG_STATIC_KEVENTS 16
#warning nope.
#endif

#ifndef CONFIG_SYSCALL_RETRY
#define CONFIG_SYSCALL_RETRY 64
#elif CONFIG_SYSCALL_RETRY < 8
#undef CONFIG_SYSCALL_RETRY
#define CONFIG_SYSCALL_RETRY 16
#warning nope.
#endif

/*
 * Manage retry state for limiting the number of times we'll accept EINTR.
 */
#define _RETRY_STATE _avail_retries
#define RETRY_STATE_INIT int _RETRY_STATE = CONFIG_SYSCALL_RETRY
#define LIMITED_RETRY() do { \
	if (_RETRY_STATE > 0) { \
		errno = 0; \
		--_RETRY_STATE; \
		goto RETRY_SYSCALL; \
	} \
} while(0);
#define UNLIMITED_RETRY() errno = 0; goto RETRY_SYSCALL;

typedef int kpoint_t; /* file descriptor */
typedef int kerror_t; /* kerror error identifier (errno) */

struct Interface {
	PyObject_HEAD
	PyObj kif_kset; /* storage for objects referenced by the kernel */
	PyObj kif_cancellations; /* cancel bucket */

	kpoint_t kif_kqueue; /* kqueue(2) fd */
	kevent_t kif_events[8];
	int kif_waiting;
};
typedef struct Interface *Interface;

static int
interface_kevent(Interface kif, int retry, int *out, kevent_t *changes, int nchanges, kevent_t *events, int nevents, const struct timespec *timeout)
{
	RETRY_STATE_INIT;
	int r = -1;

RETRY_SYSCALL:
	r = kevent(kif->kif_kqueue, changes, nchanges, events, nevents, timeout);
	if (r >= 0)
	{
		/*
		 * EV_ERROR is used in cases where kevent(2) fails after it already processed
		 * some events. In these cases, the EV_ERROR flag is used to note the case.
		 */
		if (r > 0 && events[r-1].flags & EV_ERROR)
		{
			--r;
			*out = r;
			/*
			 * XXX: Set error from EV_ERROR?
			 */
		}
		else
			*out = r;
	}
	else
	{
		/*
		 * Complete failure. Probably an interrupt or EINVAL.
		 */
		*out = 0;

		switch (errno)
		{
			case EINTR:
				/*
				 * The caller can designate whether or not retry will occur.
				 */
				switch (retry)
				{
					case -1:
						UNLIMITED_RETRY();
					break;

					case 1:
						LIMITED_RETRY();
					break;

					case 0:
						/*
						 * Purposefully allow it to fall through. Usually a signal occurred.
						 * For nucleus, falling through is appropriate as it usually means
						 * processing an empty task queue.
						 */
						*out = 0;
						return(1);
					break;
				}
			case ENOMEM:
				LIMITED_RETRY();

			default:
				return(0);
			break;
		}
	}

	return(1);
}

static PyObj
interface_repr(PyObj self)
{
	Interface kif = (Interface) self;
	PyObj rob;

	rob = PyUnicode_FromFormat("");

	return(rob);
}

/*
 * Relay to the generated transit alloc functions.
 * See the preproc blackmagic at the bottom of the file.
 */

static int
interface_init(Interface kif)
{
	const struct timespec ts = {0,0};
	int nkevents;
	kevent_t kev;

	kif->kif_kqueue = kqueue();
	if (kif->kif_kqueue == -1)
	{
		PyErr_SetFromErrno(PyExc_OSError);
		return(0);
	}

	/*
	 * Init USER filter for wait() interruptions.
	 */
	kev.udata = (void *) kif;
	kev.ident = (uintptr_t) kif;
	kev.flags = EV_ADD|EV_RECEIPT|EV_CLEAR;
	kev.filter = EVFILT_USER;
	kev.fflags = 0;
	kev.data = 0;

	if (!interface_kevent(kif, 1, &nkevents, &kev, 1, &kev, 1, &ts))
	{
		PyErr_SetFromErrno(PyExc_OSError);
		close(kif->kif_kqueue);
		kif->kif_kqueue = -1;
		return(0);
	}

#define SIGNAME(SN) \
	kev.udata = NULL; \
	kev.data = 0; \
	kev.ident = (uintptr_t) SN; \
	kev.flags = EV_ADD|EV_RECEIPT|EV_CLEAR; \
	kev.filter = EVFILT_SIGNAL; \
	kev.fflags = 0; \
\
	if (!interface_kevent(kif, 1, &nkevents, &kev, 1, &kev, 1, &ts)) \
	{ \
		PyErr_SetFromErrno(PyExc_OSError); \
		close(kif->kif_kqueue); \
		kif->kif_kqueue = -1; \
		return(0); \
	}
	KQ_SIGNALS()
#undef SIGNAME

	return(1);
}

/*
 * Interface.void()
 *
 * Close the kqueue FD, and release references.
 */
static PyObj
interface_void(PyObj self)
{
	Interface kif = (Interface) self;

	if (kif->kif_kqueue != -1)
	{
		close(kif->kif_kqueue);
		kif->kif_kqueue = -1;
	}

	Py_XDECREF(kif->kif_kset);
	kif->kif_kset = NULL;

	Py_XDECREF(kif->kif_cancellations);
	kif->kif_cancellations = NULL;

	Py_RETURN_NONE;
}

static int
acquire_kernel_ref(Interface kif, PyObj link)
{
	switch (PySet_Contains(kif->kif_kset, link))
	{
		case 1:
			PyErr_SetString(PyExc_RuntimeError, "link already referenced by kernel");
			return(-1);
		break;

		case 0:
			/* not present */
		break;

		default:
			return(-1);
		break;
	}

	return(PySet_Add(kif->kif_kset, link));
}

/*
 * Interface.track()
 */
static PyObj
interface_track(PyObj self, PyObj args)
{
	const static struct timespec ts = {0,0};

	Interface kif = (Interface) self;

	PyObj link = NULL;
	int uselink = 0;
	long l;

	int nkevents;
	kevent_t kev;

	if (!PyArg_ParseTuple(args, "l|O", &l, &link))
		return(NULL);

	if (link != NULL && link != Py_None)
	{
		if (acquire_kernel_ref(kif, link))
			return(NULL);

		uselink = 1;
		kev.udata = link;
	}
	else
		kev.udata = NULL;

	kev.data = 0;
	kev.ident = (uintptr_t) l;
	kev.flags = EV_ADD|EV_RECEIPT|EV_CLEAR;
	kev.filter = EVFILT_PROC;
	kev.fflags = NOTE_EXIT|NOTE_SIGNAL;

	if (!interface_kevent(kif, 1, &nkevents, &kev, 1, &kev, 1, &ts))
	{
		/* failed */
		if (uselink)
		{
			if (!PySet_Discard(kif->kif_kset, link))
				return(NULL);
		}

		PyErr_SetFromErrno(PyExc_OSError);
		return(NULL);
	}

	Py_RETURN_NONE;
}

static PyObj
interface_force(PyObj self)
{
	Interface kif = (Interface) self;
	struct timespec ts = {0,0};
	PyObj rob;
	kevent_t kev;
	int out = 0;

	/*
	 * Ignore force if we're not waiting or have already forced.
	 */
	if (kif->kif_waiting > 0)
	{
		kev.udata = (void *) kif;
		kev.ident = (uintptr_t) kif;
		kev.filter = EVFILT_USER;
		kev.fflags = NOTE_TRIGGER;
		kev.data = 0;
		kev.flags = EV_RECEIPT;

		if (!interface_kevent(kif, 1, &out, &kev, 1, NULL, 0, &ts))
		{
			PyErr_SetFromErrno(PyExc_OSError);
			return(NULL);
		}

		kif->kif_waiting = -1;
		rob = Py_True;
	}
	else if (kif->kif_waiting < 0)
		rob = Py_False;
	else
		rob = Py_None;

	Py_INCREF(rob);
	return(rob);
}

static int
set_timer(Interface kif, int recur, int note, unsigned long quantity, PyObj link)
{
	const static struct timespec ts = {0,0};
	int nkevents = 0;
	kevent_t kev;

	kev.ident = (uintptr_t) link;
	kev.udata = link;

	kev.fflags = note;
	kev.data = quantity;

	kev.filter = EVFILT_TIMER;
	kev.flags = EV_ADD|EV_RECEIPT|EV_ENABLE;
	if (!recur)
		kev.flags |= EV_ONESHOT;

	if (!interface_kevent(kif, 1, &nkevents, &kev, 1, &kev, 1, &ts))
	{
		PyErr_SetFromErrno(PyExc_OSError);
		return(0);
	}

	return(1);
}

static int
note_unit(int unit)
{
	const int ms = (0xCE << 2) | 0xBC;
	int note;

	switch (unit)
	{
		case 'n':
			note = NOTE_NSECONDS;
		break;

		case 'm':
			note = 0; /* milliseconds */
		break;

		case 'u':
		case ms:
			note = NOTE_USECONDS;
		break;

		case 's':
			note = NOTE_SECONDS;
		break;

		default:
			PyErr_Format(PyExc_ValueError, "invalid unit code '%c' for timer", unit);
			note = -1;
		break;
	}

	return(note);
}

static PyObj
interface_alarm(PyObj self, PyObj args, PyObj kw)
{
	const static char *kwlist[] = {
		"link", "quantity", "unitcode", NULL,
	};

	Interface kif = (Interface) self;
	PyObj link = NULL;
	unsigned long l = 0;
	int unit = 's';
	int note;

	/*
	 * (link_object, period, unit)
	 */
	if (!PyArg_ParseTupleAndKeywords(args, kw, "Ok|C", (char **) kwlist, &link, &l, &unit))
		return(NULL);

	note = note_unit(unit);
	if (note < 0)
		return(NULL);

	if (!set_timer(kif, 0, note, l, link))
		return(NULL);

	Py_RETURN_NONE;
}

static PyObj
interface_recur(PyObj self, PyObj args, PyObj kw)
{
	const static char *kwlist[] = {
		"link", "quantity", "unitcode", NULL,
	};

	Interface kif = (Interface) self;
	PyObj link = NULL;
	unsigned long l = 0;
	int unit = 's';
	int note;

	/*
	 * (link_object, period, unit)
	 */
	if (!PyArg_ParseTupleAndKeywords(args, kw, "Ok|C", (char **) kwlist, &link, &l, &unit))
		return(NULL);

	note = note_unit(unit);
	if (note < 0)
		return(NULL);

	if (!set_timer(kif, 1, note, l, link))
		return(NULL);

	Py_RETURN_NONE;
}

static PyObj
interface_cancel(PyObj self, PyObj link)
{
	const static struct timespec ts = {0,0};
	Interface kif = (Interface) self;
	int nkevents = 0;
	kevent_t kev;

	if (link != Py_None)
	{
		kev.ident = (uintptr_t) link;
		kev.udata = 0;

		kev.fflags = 0;
		kev.data = 0;

		kev.filter = EVFILT_TIMER;
		kev.flags = EV_DELETE|EV_RECEIPT;

		if (!interface_kevent(kif, 1, &nkevents, &kev, 1, &kev, 1, &ts))
		{
			PyErr_SetFromErrno(PyExc_OSError);
			return(NULL);
		}

		/*
		 * Add to cancellation *after* successful kevent()
		 */
		if (PySet_Add(kif->kif_cancellations, link) < 0)
			return(NULL);
	}

	Py_RETURN_NONE;
}

static const char *
signal_string(int sig)
{
	switch (sig)
	{
		case SIGCONT:
			return "continue";
		break;

		case SIGTERM:
			return "terminate";
		break;

		case SIGHUP:
			return "delta";
		break;

#ifdef SIGINFO
		case SIGINFO:
			return "terminal.query";
		break;
#endif

		case SIGWINCH:
			return "terminal.delta";
		break;

		case SIGUSR1:
			return "tunnel";
		break;

		case SIGUSR2:
			return "trip";
		break;

		default:
			return "";
		break;
	}
}

static PyObj
interface_enter(PyObj self)
{
	Interface kif = (Interface) self;
	kif->kif_waiting = 1;
	Py_RETURN_NONE;
}

static PyObj
interface_exit(PyObj self, PyObj args)
{
	Interface kif = (Interface) self;
	kif->kif_waiting = 0;
	Py_RETURN_NONE;
}

/*
 * interface_wait() - collect and process traffic events
 */
static PyObj
interface_wait(PyObj self, PyObj args)
{
	struct timespec waittime = {0,0};
	struct timespec *ref = &waittime;

	Interface kif = (Interface) self;
	PyObj rob;
	int i, nkevents = 0;
	int error = 0;
	long sleeptime = -1;

	if (!PyArg_ParseTuple(args, "|l", &sleeptime))
		return(NULL);

	/*
	 * *Negative* numbers signal indefinate.
	 */
	if (sleeptime >= 0)
		waittime.tv_sec = sleeptime;
	else
		ref = NULL;

	Py_BEGIN_ALLOW_THREADS
	if (!interface_kevent(kif, 0, &nkevents, NULL, 0, kif->kif_events, CONFIG_STATIC_KEVENTS, ref))
	{
		error = 1;
	}
	Py_END_ALLOW_THREADS

	if (error)
	{
		PyErr_SetFromErrno(PyExc_OSError);
		return(NULL);
	}

	/*
	 * Process the collected events.
	 */
	rob = PyList_New(0);
	if (rob == NULL)
		return(NULL);

	for (i = 0; i < nkevents; ++i)
	{
		PyObj link;
		kevent_t *kev;
		PyObj ob;

		kev = &(kif->kif_events[i]);
		link = (PyObj) kev->udata;

		switch (kev->filter)
		{
			case EVFILT_PROC:
				ob = Py_BuildValue("(slO)", "process", (long) kev->ident, link ? link : Py_None);
				if (kev->fflags & NOTE_EXIT && link != NULL)
				{
					/* done with filter entry */

					if (PySet_Discard(kif->kif_kset, link) < 0)
					{
						/* note internal error */
					}
				}
			break;

			case EVFILT_SIGNAL:
				ob = Py_BuildValue("(ss)", "signal", signal_string(kev->ident));
			break;

			case EVFILT_TIMER:
			{
				if (link == NULL)
					/* core status? */
					continue;

				switch (PySet_Contains(kif->kif_cancellations, link))
				{
					case 1:
						if (PySet_Discard(kif->kif_kset, link) < 0)
						{
							/* error */
						}
						else if (PySet_Discard(kif->kif_cancellations, link) < 0)
						{
							/* error */
						}
						continue;
					break;
					case 0:
						/* not cancelled */
					break;
					default:
						/* -1 error */
					break;
				}

				if (kev->flags & EV_ONESHOT)
				{
					ob = Py_BuildValue("(sO)", "alarm", link);

					if (PySet_Discard(kif->kif_kset, link) < 0)
					{
						/* error */
					}
				}
				else
				{
					ob = Py_BuildValue("(sO)", "recur", link);
				}
			}
			break;

			case EVFILT_USER:
				/*
				 * event from force() method
				 */
				continue;
			break;

			default:
				/*
				 * unknown event, throw warning
				 */
				continue;
			break;
		}

		PyList_Append(rob, ob);
	}

	/*
	 * Complete timer cancellations.
	 */
	if (PySet_GET_SIZE(kif->kif_cancellations) > 0)
	{
		PyObj r = PyObject_CallMethod(kif->kif_kset, "difference_update", "O", kif->kif_cancellations);
		if (r != NULL)
			Py_DECREF(r);

		if (!PySet_Clear(kif->kif_cancellations))
		{
			/* error */
		}
	}

	return(rob);
}

static PyMethodDef
interface_methods[] = {
	{"void", (PyCFunction) interface_void,
		METH_NOARGS, PyDoc_STR(
"void()\n\n"
":returns: None\n"
"\n"
"Destroy the Interface instance, closing any file descriptors managed by the object.\n"
"Also destroy the internal set-object for holding kernel references.\n"
)},

	{"track", (PyCFunction) interface_track, METH_VARARGS,
		PyDoc_STR(
"track(link_object, pid)\n\n"
":returns: None\n"
":rtype: NoneType\n"
"\n"
"Watch a process so that an event will be generated when it exits.\n"
)},

	{"alarm", (PyCFunction) interface_alarm, METH_VARARGS|METH_KEYWORDS,
		PyDoc_STR(
"alarm(link_object, period, unit)\n\n"
":returns: None\n"
":rtype: NoneType\n"
"\n"
"Allocate a one-time timer that will cause an event after the designed period.\n"
)},

	{"recur", (PyCFunction) interface_recur, METH_VARARGS|METH_KEYWORDS,
		PyDoc_STR(
"recur(link_object, period, unit)\n\n"
":returns: None\n"
":rtype: NoneType\n"
"\n"
"Allocate a recurring timer that will cause an event at the designed frequency.\n"
)},

	{"cancel", (PyCFunction) interface_cancel, METH_O,
		PyDoc_STR(
"recur(link_object)\n\n"
":returns: None\n"
":rtype: NoneType\n"
"\n"
"Cancel a timer, recurring or once, using the link that the timer was allocated with.\n"
)},

	{"force", (PyCFunction) interface_force, METH_NOARGS,
		PyDoc_STR(
":returns: None or True or False\n"
"\n"
"Cause a corresponding :py:meth:`.wait` call to stop waiting **if** the Interface\n"
"instance is inside a with-statement block::\n"
"\n"
"	with kinterface:\n"
"		kinterface.wait()\n"
"\n"
"\n"
)},

	{"wait",
		(PyCFunction) interface_wait, METH_VARARGS,
		PyDoc_STR(
":returns: Sequence of events that occurred while waiting.\n"
":rtype: list\n"
"\n"
"Normally executed after entering a with-statement block.\n"
"If executed outside, the :py:meth:`.force` method will not interrupt the system call."
)},

	{"__enter__",
		(PyCFunction) interface_enter, METH_NOARGS,
		PyDoc_STR(
":returns: Sequence of events that occurred while waiting.\n"
":rtype: list\n"
"\n"
"Enter waiting state."
)},

	{"__exit__",
		(PyCFunction) interface_exit, METH_VARARGS,
		PyDoc_STR(
":returns: None.\n"
"\n"
"Leave waiting state."
)},

	{NULL,},
};

static PyMemberDef interface_members[] = {
	{"waiting", T_PYSSIZET, offsetof(struct Interface, kif_waiting), READONLY,
		PyDoc_STR("Whether or not the Interface object is with statement block.")},
	{NULL,},
};

static void
interface_dealloc(PyObj self)
{
	Interface kif = (Interface) self;

	Py_XDECREF(kif->kif_kset);
	kif->kif_kset = NULL;
	Py_XDECREF(kif->kif_cancellations);
	kif->kif_cancellations = NULL;

	if (kif->kif_kqueue != -1)
	{
		close(kif->kif_kqueue);
		PyErr_WarnFormat(PyExc_ResourceWarning, 0, QPATH("Interface") " instance not voided before deallocation");
	}
}

static int
interface_clear(PyObj self)
{
	Interface kif = (Interface) self;
	Py_CLEAR(kif->kif_kset);
	Py_CLEAR(kif->kif_cancellations);
	return(0);
}

static int
interface_traverse(PyObj self, visitproc visit, void *arg)
{
	Interface kif = (Interface) self;
	Py_VISIT(kif->kif_kset);
	Py_VISIT(kif->kif_cancellations);
	return(0);
}

static PyObj
interface_new(PyTypeObject *subtype, PyObj args, PyObj kw)
{
	static char *kwlist[] = {NULL,};
	Interface kif;

	if (!PyArg_ParseTupleAndKeywords(args, kw, "", kwlist))
		return(NULL); XCOVERAGE

	kif = (Interface) subtype->tp_alloc(subtype, 0);
	if (kif == NULL)
		return(NULL); XCOVERAGE

	kif->kif_kqueue = -1;
	kif->kif_waiting = 0;

	kif->kif_kset = PySet_New(0);
	if (kif->kif_kset == NULL)
	{
		Py_DECREF(kif);
		return(NULL);
	}

	kif->kif_cancellations = PySet_New(0);
	if (kif->kif_cancellations == NULL)
	{
		Py_DECREF(kif);
		return(NULL);
	}

	if (!interface_init(kif))
	{
		Py_DECREF(((PyObj) kif));
		return(NULL);
	}

	return((PyObj) kif);
}

PyDoc_STRVAR(interface_doc,
"The kernel Interface implementation providing event driven signalling for control signals and subprocess exits.");

PyTypeObject
InterfaceType = {
	PyVarObject_HEAD_INIT(NULL, 0)
	QPATH("Interface"),			/* tp_name */
	sizeof(struct Interface),	/* tp_basicsize */
	0,									/* tp_itemsize */
	interface_dealloc,			/* tp_dealloc */
	NULL,								/* tp_print */
	NULL,								/* tp_getattr */
	NULL,								/* tp_setattr */
	NULL,								/* tp_compare */
	NULL,								/* tp_repr */
	NULL,								/* tp_as_number */
	NULL,								/* tp_as_sequence */
	NULL,								/* tp_as_mapping */
	NULL,								/* tp_hash */
	NULL,								/* tp_call */
	NULL,								/* tp_str */
	NULL,								/* tp_getattro */
	NULL,								/* tp_setattro */
	NULL,								/* tp_as_buffer */
	Py_TPFLAGS_BASETYPE|
	Py_TPFLAGS_HAVE_GC|
	Py_TPFLAGS_DEFAULT,			/* tp_flags */
	interface_doc,					/* tp_doc */
	interface_traverse,			/* tp_traverse */
	interface_clear,				/* tp_clear */
	NULL,								/* tp_richcompare */
	0,									/* tp_weaklistoffset */
	NULL,								/* tp_iter */
	NULL,								/* tp_iternext */
	interface_methods,			/* tp_methods */
	interface_members,			/* tp_members */
	NULL,								/* tp_getset */
	NULL,								/* tp_base */
	NULL,								/* tp_dict */
	NULL,								/* tp_descr_get */
	NULL,								/* tp_descr_set */
	0,									/* tp_dictoffset */
	NULL,								/* tp_init */
	NULL,								/* tp_alloc */
	interface_new,					/* tp_new */
};

static PyObj
set_process_title(PyObj mod, PyObj title)
{
	PyObj bytes;

#ifndef __MACH__
	/*
	 * no support on darwin
	 */
	bytes = PyUnicode_AsUTF8String(title);

	if (bytes == NULL)
		return(NULL);

	setproctitle("%s", PyBytes_AS_STRING(bytes));
	Py_DECREF(bytes);
#endif

	Py_RETURN_NONE;
}

static PyObj
execfile(PyObj mod, PyObj args, PyObj kw)
{
	pid_t child = 0;
	int err = 0;

	PyObj fdmap, cargs;

	char *path;
	char **argv = NULL;
	char **envp = NULL;

	short flags = 0;
	posix_spawnattr_t sa;
	posix_spawn_file_actions_t fa;

	if (!PyArg_ParseTuple(args, "OsO", &fdmap, &path, &cargs))
		return(NULL);

	if (posix_spawnattr_init(&sa) != 0)
	{
		PyErr_SetFromErrno(PyExc_OSError);
		return(NULL);
	}

	if (posix_spawn_file_actions_init(&fa) != 0)
	{
		PyErr_SetFromErrno(PyExc_OSError);
		posix_spawnattr_destroy(&sa);
		errno = 0; /* ignore any error from destroy */
		return(NULL);
	}

#ifdef POSIX_SPAWN_CLOEXEC_DEFAULT
	flags |= POSIX_SPAWN_CLOEXEC_DEFAULT;
#endif

#if 0
	When Requested:
	flags |= POSIX_SPAWN_SETPGROUP:
#endif

	if (posix_spawnattr_setflags(&sa, flags) != 0)
	{
		err = 1;
		PyErr_SetFromErrno(PyExc_OSError);
	}

	/*
	 * Handle the fdmap parameter.
	 */
	if (!err)
	{
		int fd, newfd, r;

		PyLoop_ForEachTuple(fdmap, "ii", &fd, &newfd)
		{
			if (newfd >= 0)
				r = posix_spawn_file_actions_adddup2(&fa, fd, newfd);
			else
				r = posix_spawn_file_actions_addinherit_np(&fa, fd);

			if (r != 0)
			{
				PyErr_SetFromErrno(PyExc_OSError);
				break;
			}
		}
		PyLoop_CatchError(fdmap)
		{
			err = 1;
		}
		PyLoop_End(fdmap)
	}

	/*
	 * Environment
	 */
	if (!err && kw != NULL)
	{
		int k = 0;
		Py_ssize_t keysize, valuesize, dl = PyDict_Size(kw);
		char *key, *value;

		envp = malloc(sizeof(void *) * dl);
		if (envp == NULL)
		{
			PyErr_SetFromErrno(PyExc_OSError);
			err = 1;
		}
		else
		{
			PyLoop_ForEachDictItem(kw, "s#s#", &key, &keysize, &value, &valuesize)
			{
				envp[k] = malloc(keysize);
				envp[k+1] = malloc(valuesize);

				strncpy(envp[k], key, keysize);
				strncpy(envp[k+1], value, valuesize);

				k += 2;
			}
			PyLoop_CatchError(kw)
			{
				err = 1;
			}
			PyLoop_End(kw)
		}
	}

	/*
	 * Command Arguments
	 */
	if (!err && cargs != NULL)
	{
		int k = 0;
		char *value;
		Py_ssize_t valuesize, al = PySequence_Length(cargs);

		argv = malloc(sizeof(void *) * al);
		if (argv == NULL)
		{
			PyErr_SetFromErrno(PyExc_OSError);
			err = 1;
		}
		else
		{
			PyLoop_ForEachTuple(cargs, "s#", &value, &valuesize)
			{
				argv[k] = malloc(valuesize);

				strncpy(argv[k], value, valuesize);
				k += 1;
			}
			PyLoop_CatchError(cargs)
			{
				err = 1;
			}
			PyLoop_End(cargs)
		}
	}

	/*
	 * run the spawn
	 */
	if (!err)
	{
		if (posix_spawn(&child, (const char *) path, &fa, &sa, argv, envp) != 0)
		{
			PyErr_SetFromErrno(PyExc_OSError);
			err = 1;
		}
	}

	/*
	 * cleanup code. errors here are ignored.
	 */

	if (argv != NULL)
	{
		int i = 0;

		for (i = 0; argv[i] != NULL; ++i)
			free(argv[i]);
		free(argv);
	}

	if (envp != NULL)
	{
		int i = 0;

		for (i = 0; envp[i] != NULL; ++i)
			free(envp[i]);
		free(envp);
	}

	if (posix_spawnattr_destroy(&sa) != 0)
	{
		/*
		 * A warning would be appropriate.
		PyErr_SetFromErrno(PyExc_OSError);
		 */
	}

	if (posix_spawn_file_actions_destroy(&fa) != 0)
	{
		/*
		 * A warning would be appropriate.
		PyErr_SetFromErrno(PyExc_OSError);
		 */
	}

	if (err)
		return(NULL);

	/*
	 * Spawned a subprocess.
	 */
	return(PyLong_FromLong((long) child));
}

METHODS() = {
	{"set_process_title",
		(PyCFunction) set_process_title, METH_O,
		PyDoc_STR(
":returns: None\n"
"\n"
"Set the process title on supporting platforms."
)},

	{"execfile",
		(PyCFunction) execfile, METH_O,
		PyDoc_STR(
":returns: pid\n"
":rtype: int\n"
"\n"
"Execute the given file in a subprocess with the given arguments."
)},

	{NULL,}
};

#define PYTHON_TYPES() \
	ID(Interface)

INIT(PyDoc_STR("Kernel interfaces for supporting nucleus based process management.\n"))
{
	PyObj mod = NULL;

#if TEST()
	Py_XDECREF(__EOVERRIDE__);
	__EOVERRIDE__ = PyDict_New();
	if (__EOVERRIDE__ == NULL)
		return(NULL); XCOVERAGE

	Py_XDECREF(__POVERRIDE__);
	__POVERRIDE__ = PyDict_New();
	if (__POVERRIDE__ == NULL)
		return(NULL); XCOVERAGE
#endif

	CREATE_MODULE(&mod);
	if (mod == NULL)
		return(NULL); XCOVERAGE

#if TEST()
	PyModule_AddObject(mod, "EOVERRIDE", __EOVERRIDE__);
	PyModule_AddObject(mod, "POVERRIDE", __POVERRIDE__);
#endif

	/*
	 * Initialize Transit types.
	 */
#define ID(NAME) \
	if (PyType_Ready((PyTypeObject *) &( NAME##Type ))) \
		goto error; \
	if (PyModule_AddObject(mod, #NAME, (PyObj) &( NAME##Type )) < 0) \
		goto error;
	PYTHON_TYPES()
#undef ID

	return(mod);
error:
	DROP_MODULE(mod);
	return(NULL);
}
/*
 * vim: ts=3:sw=3:noet:
 */
#if 0
"""
#endif
