"""The exporter interface: one TIA (or a stand-in) per archive. Implementations: fake.FakeExporter (tests, the
window's development) and bridge.BridgeExporter (TiaBridge as a child over MCP stdio; later tia.exe mcp).

Calls block; the run checks for a cancel between them. A failure raises ExportFailed with the plain words and the
Siemens error; a protected project or a wrong password raises NeedsLogin.
"""

# What the report reads (TiaBridge full_export parts); the cache key holds it. PARTS always; HMI_PARTS with --hmi:
# every HMI device's parts the report compares (TiaBridge\Tools\FullExport.ps1 names them; folders hmi\ or
# hmi\<device>\) and the project graphics the screens show (project\graphics).
PARTS = ('blocks', 'dbs', 'types', 'plc_tags', 'library_types')
HMI_PARTS = ('hmi_screens', 'hmi_templates', 'hmi_popups', 'hmi_slideins', 'hmi_screen_globals', 'hmi_tags',
             'hmi_textlists', 'hmi_graphiclists', 'hmi_scripts', 'hmi_cycles', 'hmi_connections', 'graphics')
PART_TEXT = {'blocks': 'blocks', 'dbs': 'DBs', 'types': 'UDTs', 'plc_tags': 'PLC tag tables',
             'library_types': 'library types',
             'hmi_screens': 'HMI screens', 'hmi_templates': 'HMI templates', 'hmi_popups': 'HMI pop-ups',
             'hmi_slideins': 'HMI slide-ins', 'hmi_screen_globals': 'HMI global elements', 'hmi_tags': 'HMI tag tables',
             'hmi_textlists': 'HMI text lists', 'hmi_graphiclists': 'HMI graphic lists', 'hmi_scripts': 'HMI scripts',
             'hmi_cycles': 'HMI cycles', 'hmi_connections': 'HMI connections', 'graphics': 'project graphics'}
# One object of a part, for "Not in the report" (the part's text without the plural)
PART_ITEM = {'plc_tags': 'PLC tag table',
             'hmi_screens': 'HMI screen', 'hmi_templates': 'HMI template', 'hmi_popups': 'HMI pop-up',
             'hmi_slideins': 'HMI slide-in', 'hmi_screen_globals': 'HMI global element', 'hmi_tags': 'HMI tag table',
             'hmi_textlists': 'HMI text list', 'hmi_graphiclists': 'HMI graphic list', 'hmi_scripts': 'HMI script',
             'hmi_cycles': 'HMI cycle', 'hmi_connections': 'HMI connection', 'graphics': 'project graphic',
             'library_types': 'library type'}


def parts_of(hmi):
    """The parts a run exports: the PLC's, with hmi also the HMI's."""
    return PARTS + (HMI_PARTS if hmi else ())


def part_where(part, device=''):
    """'HMI screens of Panel_1' (a part on one device), 'blocks'."""
    text = PART_TEXT.get(part, part)
    return '%s of %s' % (text, device) if device else text


def item_name(name, part, device=''):
    """An object's name for "Not in the report": 'Overview (HMI screen, Panel_1)', 'Secret (library type)';
    a PLC block's name as it is."""
    what = [x for x in (PART_ITEM.get(part), device) if x]
    return '%s (%s)' % (name, ', '.join(what)) if what else name


class ExportFailed(Exception):
    """plain: one sentence for the user; err: the Siemens error (dict as TiaBridge gives it) or a refusal text."""

    def __init__(self, plain, err=None):
        super().__init__(plain)
        self.plain = plain
        self.err = err


class NeedsLogin(ExportFailed):
    """kind: umc_login (open) or safety_password (compile); wrong: a login was given and refused."""

    def __init__(self, kind, plain, err=None, wrong=False):
        super().__init__(plain, err)
        self.kind = kind
        self.wrong = wrong


class Hooks:
    """What an exporter reports while it works. The run passes its own; this one ignores everything."""

    def phase(self, name):
        """'open': TIA has started, the project is being unpacked or opened now."""

    def tia(self, pid):
        """The TIA process id, as soon as known (the window keeps it for a hard stop)."""

    def progress(self, done, total, item):
        pass

    def log(self, level, text):
        pass

    def diag(self, text):
        """A diagnostic line (log.txt and stderr only)."""

    def prompt(self, text, answer):
        """A TIA prompt the exporter answered (no one could see it)."""

    def cancelled(self):
        return False


class OpenResult:
    def __init__(self, pid=0, times=None, upgraded=False, notes=()):
        self.pid = pid
        self.times = times or {}         # ms of 'start' and 'open' when the exporter knows them
        self.upgraded = upgraded
        self.notes = list(notes)


class ExportResult:
    """not_exported: [{name, why}]; cancelled: a cancel stopped it between parts (the export is unfinished)."""

    def __init__(self, not_exported=(), cancelled=False, counts=None):
        self.not_exported = list(not_exported)
        self.cancelled = cancelled
        self.counts = counts or {}


class Exporter:
    name = 'exporter'
    version = '0'
    needs_tia = True

    def open(self, source, export_dir, hooks, login=None):
        """Starts TIA and opens a copy of source (inputs.Source); exports will go to export_dir. login: {user,
        password} for a UMC-protected project. Returns OpenResult."""
        raise NotImplementedError

    def compile(self, hooks, safety_password=None):
        """Compiles the copy (never saved). Returns the names still failing."""
        raise NotImplementedError

    def export(self, parts, hooks):
        """Exports `parts` into export_dir. Returns ExportResult."""
        raise NotImplementedError

    def close(self, hooks):
        """Closes the project without saving, ends TIA, removes the copy."""
        raise NotImplementedError

    def kill(self):
        """Ends the exporter and its TIA at once (a hung call, the run ending in an error)."""
        raise NotImplementedError

    def login_hint(self, kind):
        """A line for the login dialog (the fake: the sample's password), or None."""
        return None
