"""Fixture project repos for the hmipreview tests: a temp directory with git, TIA exports under hmi/<kind>,
generated documents under hmi/generated/<kind>, tiabridge.json, planned.json and handbuilt.json. device= puts a
file into the folder of that HMI device, hmi/<device>/... (a project with several HMI devices).

Documents are written as SimaticML in the shape of docs/agent/wincc-comfort-openness.md section 4.
"""
import json
import os
import shutil
import subprocess
import tempfile
from xml.sax.saxutils import escape

TP1200 = 'OrderNumber:6AV2 124-0MC01-0AX0/17.0.0.0'

KIND_DIRS = {'screen': 'screens', 'template': 'templates', 'popup': 'popups', 'textlist': 'textlists'}
ROOT_TAGS = {'screen': 'Hmi.Screen.Screen', 'template': 'Hmi.Screen.ScreenTemplate',
             'popup': 'Hmi.Screen.ScreenPopup', 'textlist': 'Hmi.TextGraphicList.TextList'}


FULL_SETTING = 'WithDefaults, WithReadOnly'     # DocumentInfo/ExportSetting of a full export

# Full-export shape: the non-geometry attributes a V20 Update 7 full export (WithDefaults | WithReadOnly) writes on
# every object of a type, with the values most project B objects carry (hmi/full, 2026-10-06). item() and document()
# start from these, so fixture documents look like full exports; geometry and names come from each test. A test
# drops one with Name=None, or builds an object as written with full=False.
FULL = {
    'Hmi.Screen.Rectangle': dict(
        BackColor='255, 255, 255', BackFillStyle='Solid', BorderColor='24, 28, 49', BorderWidth=0,
        EdgeStyle='Solid', Flashing='None', RoundCornerHeight=0, RoundCornerWidth=0, TabIndex=-1,
        UseDesignColorSchema='false'),
    'Hmi.Screen.TextField': dict(
        BackColor='255, 255, 255', BackFillStyle='Transparent', BorderBackColor='101, 103, 115',
        BorderColor='71, 73, 87', BorderWidth=0, BottomMargin=0, CornerRadius=0, EdgeStyle='Double',
        FitToLargest='false', Flashing='None', ForeColor='40, 40, 40', HorizontalAlignment='Left', LeftMargin=0,
        RightMargin=0, TabIndex=-1, TextOrientation='Horizontal', TopMargin=0, UseDesignColorSchema='false',
        VerticalAlignment='Top'),
    'Hmi.Screen.Button': dict(
        BackColor='224, 224, 224', BackFillStyle='Solid', BitNumber=0, BorderBackColor='105, 105, 105',
        BorderColor='176, 176, 176', BorderWidth=1, CornerRadius=0, CornerStyle='Pointed', EdgeStyle='Solid',
        Enabled='true', FirstGradientColor='131, 132, 142', FirstGradientOffset=15, FitToLargest='false',
        Flashing='None', FocusColor='72, 116, 160', FocusWidth=2, ForeColor='40, 40, 40',
        HorizontalAlignment='Center', HorizontalPictureAlignment='Center', HotKey=0,
        MiddleGradientColor='99, 101, 113', Mode='Text', PictureAreaBottomMargin=0, PictureAreaLeftMargin=0,
        PictureAreaRightMargin=0, PictureAreaTopMargin=0, PictureAutoSizing='StretchPicture',
        SecondGradientColor='88, 90, 103', SecondGradientOffset=15, TabIndex=0, TextAreaBottomMargin=0,
        TextAreaLeftMargin=0, TextAreaRightMargin=0, TextAreaTopMargin=0, TextOrientation='Horizontal',
        UseDesignColorSchema='false', UseFirstGradient='false', UseSecondGradient='false',
        UseTwoHandOperation='false', VerticalAlignment='Middle', VerticalPictureAlignment='Middle'),
    'Hmi.Screen.IOField': dict(
        AboveUpperLimitColor='237, 88, 97', BackColor='230, 230, 230', BackFillStyle='Solid',
        BelowLowerLimitColor='241, 161, 44', BorderBackColor='230, 230, 230', BorderColor='204, 204, 204',
        BorderWidth=1, BottomMargin=0, CornerRadius=0, DataFormat='Decimal', EdgeStyle='Double', Enabled='true',
        FieldLength=2, FitToLargest='false', Flashing='None', ForeColor='40, 40, 40', FormatPattern='99',
        HiddenInput='false', HorizontalAlignment='Right', LeftMargin=0, Mode='Output', RightMargin=4,
        ShiftDecimalPoint=0, ShowLeadingZeros='false', TabIndex=-1, TextOrientation='Horizontal', TopMargin=0,
        Unit='', UseDesignColorSchema='false', UseTwoHandOperation='false', VerticalAlignment='Middle'),
    'Hmi.Screen.SymbolicIOField': dict(
        AboveUpperLimitColor='237, 88, 97', BackColor='230, 230, 230', BackFillStyle='Solid',
        BelowLowerLimitColor='241, 161, 44', BitNumber=0, BorderBackColor='230, 230, 230',
        BorderColor='204, 204, 204', BorderWidth=1, BottomMargin=0, CornerRadius=0, CountVisibleItems=3,
        EdgeStyle='Double', Enabled='true', EvenRowBackColor='230, 230, 232', FitToLargest='false',
        Flashing='None', FlashingOnLimitViolation='false', ForeColor='40, 40, 40', HorizontalAlignment='Right',
        LeftMargin=0, Mode='Output', OnValue=1, RightMargin=4, SelectBackColor='0, 0, 0',
        SelectForeColor='255, 255, 255', ShowDropDownButton='true', ShowDropDownList='true', TabIndex=-1,
        TextOrientation='Horizontal', TopMargin=0, UseDesignColorSchema='false', VerticalAlignment='Middle'),
    'Hmi.Screen.Line': dict(
        BackColor='255, 255, 255', Color='104, 104, 104', EndStyle='NoEnd', FillStyle='Transparent',
        Flashing='None', LineEndShapeStyle='Round', LineWidth=1, StartStyle='NoEnd', Style='Solid', TabIndex=-1,
        UseDesignColorSchema='false'),
    'Hmi.Screen.Circle': dict(
        BackColor='104, 104, 104', BackFillStyle='Solid', BorderColor='40, 40, 40', BorderWidth=1,
        EdgeStyle='Solid', Flashing='None', TabIndex=-1, UseDesignColorSchema='false'),
    'Hmi.Screen.Polygon': dict(
        BackColor='255, 255, 0', BackFillStyle='Solid', BorderColor='24, 28, 49', BorderWidth=1,
        EdgeStyle='Solid', Flashing='None', TabIndex=-1, UseDesignColorSchema='false'),
    'Hmi.Screen.GraphicView': dict(
        AutoSizing='StretchPicture', BackColor='255, 255, 255', BackFillStyle='Transparent',
        BorderColor='0, 0, 0', BorderWidth=0, EdgeStyle='Solid', FitToLargest='false', Flashing='None',
        TabIndex=-1, TransparentColor='255, 0, 255', UseTransparentColor='false'),
    'Hmi.Screen.Clock': dict(
        Analog='false', BackFillStyle='Solid', BorderBackColor='109, 109, 121', BorderColor='52, 54, 68',
        BorderWidth=1, CornerRadius=0, DialColor='230, 230, 230', EdgeStyle='Double', Flashing='None',
        TabIndex=-1, UseDesignColorSchema='false'),
    'Hmi.Screen.FaceplateInstance': dict(Resizing='None', TabIndex=-1),
    'Hmi.Screen.Group': dict(TabIndex=-1),
}
FULL_ROOT = {
    'screen': dict(ActiveLayer=0, BackColor='224, 224, 224', GridColor='0, 0, 0', Height=800, Visible='true',
                   Width=1280),
    'template': dict(ActiveLayer=0, BackColor='192, 192, 192', GridColor='0, 0, 0', Height=800,
                     SetTabOrderInFront='true', Width=1280),
    'popup': dict(ActiveLayer=0, BackColor='240, 240, 240', GridColor='0, 0, 0',
                  ScrollbarBackgroundColor='230, 230, 232', ScrollbarForegroundColor='24, 28, 49'),
    'textlist': {},
}


def attrs_xml(attrs):
    return ''.join('<%s>%s</%s>' % (k, escape(str(v)), k) for k, v in sorted(attrs.items()) if v is not None)


def full_attrs(base, attrs, full):
    merged = dict(base) if full else {}
    merged.update(attrs)
    return merged


def item(type_, name, children='', full=True, **attrs):
    """One screen item in full-export shape, e.g. item('Hmi.Screen.Rectangle', 'rect1', Left=10, Top=90, Width=100,
    Height=50): FULL[type_] overridden by attrs (None drops one); full=False writes attrs alone."""
    attrs['ObjectName'] = name
    attrs = full_attrs(FULL.get(type_, {}), attrs, full)
    return ('<%s ID="0" CompositionName="ScreenItems"><AttributeList>%s</AttributeList>%s</%s>'
            % (type_, attrs_xml(attrs), children, type_))


def rect(name, left=10, top=90, width=100, height=50, **attrs):
    return item('Hmi.Screen.Rectangle', name, Left=left, Top=top, Width=width, Height=height, **attrs)


def group(name, *members):
    return item('Hmi.Screen.Group', name, '<ObjectList>%s</ObjectList>' % ''.join(members))


# What a full export of a cycle writes beside CycleTime, CycleUnit and Name, at TIA's defaults [EXPORT] (2026-11-12): a
# minimal export of a cycle at its defaults leaves all four out.
CYCLE_DEFAULTS = {'StartAtStartingPoint': 'true', 'StartingPoint': '****-**-**T**:**:**', 'TriggerAtShutdown': 'false',
                  'TriggerAtStartup': 'false'}


def cycle(name, export_setting=FULL_SETTING, full=True, root='Hmi.Cycle.Cycle', **attrs):
    """A cycle document of 2 s in export shape: CYCLE_DEFAULTS overridden by attrs (None drops one); full=False writes
    the others alone, as a minimal export of a cycle at its defaults does; export_setting None leaves it out."""
    attrs = full_attrs(CYCLE_DEFAULTS, {'CycleTime': 2, 'CycleUnit': 'Second', 'Name': name, **attrs}, full)
    setting = '<ExportSetting>%s</ExportSetting>' % export_setting if export_setting else ''
    return ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20" />'
            '<DocumentInfo><Created>2026-11-12T00:00:00</Created>%s</DocumentInfo><%s ID="0"><AttributeList>%s'
            '</AttributeList></%s></Document>\n' % (setting, root, attrs_xml(attrs), root))


def document(kind, name, items=(), template=None, full=True, export_setting=FULL_SETTING, **attrs):
    """A screen / template / pop-up document with one layer holding the items, in full-export shape: root
    attributes FULL_ROOT[kind] overridden by attrs, DocumentInfo/ExportSetting export_setting (None leaves it
    out). full=False writes the root attributes as given."""
    tag = ROOT_TAGS[kind]
    attrs['Name'] = name
    attrs = full_attrs(FULL_ROOT[kind], attrs, full)
    links = '<LinkList><Template TargetID="@OpenLink"><Name>%s</Name></Template></LinkList>' % escape(template) \
        if template else ''
    layer = ('<Hmi.Screen.ScreenLayer ID="0" CompositionName="Layers"><AttributeList><Index>0</Index>'
             '<Name /><VisibleES>true</VisibleES></AttributeList><ObjectList>%s</ObjectList>'
             '</Hmi.Screen.ScreenLayer>' % ''.join(items))
    body = ('<%s ID="0"><AttributeList>%s</AttributeList>%s<ObjectList>%s</ObjectList></%s>'
            % (tag, attrs_xml(attrs), links, layer, tag))
    setting = '<ExportSetting>%s</ExportSetting>' % export_setting if export_setting else ''
    return ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20" />'
            '<DocumentInfo><Created>2026-10-06T00:00:00</Created>%s</DocumentInfo>%s</Document>\n'
            % (setting, body))


class FixtureRepo:
    """A project repo on disk. Call cleanup() (or use addCleanup) when done."""

    def __init__(self, type_identifier=TP1200, start_screen=None, git=True):
        self.path = tempfile.mkdtemp(prefix='hmipreview-')
        cfg = {'projectName': 'Fixture', 'hmiDevices': ['HMI_1']}
        if type_identifier is not None:
            cfg['hmiTypeIdentifier'] = type_identifier
        if start_screen is not None:
            cfg['startScreen'] = start_screen
        self.write('tiabridge.json', json.dumps(cfg, indent=2))
        os.makedirs(os.path.join(self.path, 'hmi'), exist_ok=True)
        if git:
            self.git('init', '-q')
            self.git('config', 'user.email', 'fixture@example.invalid')
            self.git('config', 'user.name', 'Fixture')

    def cleanup(self):
        def onerror(func, p, _exc):          # git marks pack files read-only on Windows
            os.chmod(p, 0o700)
            func(p)
        shutil.rmtree(self.path, onexc=onerror)

    def write(self, rel, text):
        full = os.path.join(self.path, *rel.split('/'))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w', encoding='utf-8-sig', newline='\r\n') as f:
            f.write(text)
        return rel

    @staticmethod
    def base(device=None):
        """hmi, or hmi/<device> for a device folder."""
        return 'hmi/' + device if device else 'hmi'

    def export(self, kind, name, text, folder='', device=None):
        """A TIA export: hmi/[<device>/]<kind dir>/<folder>/<name>.xml."""
        parts = [self.base(device), KIND_DIRS[kind]] + ([folder] if folder else []) + [name + '.xml']
        return self.write('/'.join(parts), text)

    def generated(self, kind, name, text, folder='', device=None):
        parts = [self.base(device), 'generated', KIND_DIRS[kind]] + ([folder] if folder else []) + [name + '.xml']
        return self.write('/'.join(parts), text)

    def faceplate_type(self, name, versions, folder=''):
        """TiaBridge export of a faceplate type (kind faceplate_type): the type index
        library/faceplates/<folder>/<name>.type.json {name, folder, versions}. The version metadata files the bridge
        writes beside it are not read by the preview, so the fixture leaves them out."""
        base = '/'.join(['library', 'faceplates'] + ([folder] if folder else []))
        return self.write('%s/%s.type.json' % (base, name),
                          json.dumps({'name': name, 'folder': folder, 'versions': list(versions)}, indent=2))

    def panel(self, panel='TP1200 Comfort', width=1280, height=800, portrait=False, order_number=None, device=None):
        """The declared target panel hmi/[<device>/]panel.json (written by python -m hmipreview panel or
        hmixml.begin)."""
        data = {'panel': panel, 'width': width, 'height': height, 'portrait': portrait}
        if order_number is not None:
            data['orderNumber'] = order_number
        return self.write(self.base(device) + '/panel.json', json.dumps(data, indent=2))

    def planned(self, entries, device=None):
        return self.write(self.base(device) + '/generated/planned.json', json.dumps(entries, indent=2))

    def handbuilt(self, entries, device=None):
        return self.write(self.base(device) + '/handbuilt.json', json.dumps(entries, indent=2))

    def config(self, **keys):
        """Sets keys of tiabridge.json (None removes one)."""
        with open(os.path.join(self.path, 'tiabridge.json'), encoding='utf-8-sig') as f:
            cfg = json.load(f)
        for k, v in keys.items():
            if v is None:
                cfg.pop(k, None)
            else:
                cfg[k] = v
        self.write('tiabridge.json', json.dumps(cfg, indent=2))

    def git(self, *args, env=None):
        return subprocess.run(['git', '-C', self.path] + list(args), check=True, capture_output=True,
                              text=True, env=None if env is None else {**os.environ, **env}).stdout

    def commit(self, message='fixture', date=None):
        """Commit everything; date (e.g. '2026-10-06T10:00:00+02:00') sets author and committer date."""
        self.git('add', '-A')
        env = None if date is None else {'GIT_COMMITTER_DATE': date, 'GIT_AUTHOR_DATE': date}
        self.git('commit', '-q', '--allow-empty', '-m', message, env=env)

    def touch(self, rel, timestamp):
        """Set the mtime of a repo file (seconds since the epoch)."""
        os.utime(os.path.join(self.path, *rel.split('/')), (timestamp, timestamp))
