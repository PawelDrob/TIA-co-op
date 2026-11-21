"""Slide-ins, the global elements and the screen overview: TiaBridge imports them from their export folders
(hmi/slideins, hmi/global) after these rules (docs/agent/openness-hmi.md section 2, Slide-ins and global screens).
"""
import unittest

from hmipreview import validate
from Tests.fixture import FixtureRepo, export_document, rect


def slidein(edge='Top', root='Hmi.Screen.ScreenSlidein'):
    return export_document('<%s ID="0"><AttributeList><Dimension>267</Dimension><SlideinType>%s</SlideinType>'
                           '</AttributeList></%s>' % (root, edge, root))


def global_elements(items=(), root='Hmi.Screen.ScreenGlobalElements'):
    return export_document('<%s ID="0"><AttributeList><BackColor>182, 182, 182</BackColor></AttributeList><ObjectList>'
                           '<Hmi.Screen.ScreenLayer ID="1" CompositionName="Layers"><AttributeList><Index>0</Index>'
                           '<Name /></AttributeList>%s</Hmi.Screen.ScreenLayer></ObjectList></%s>'
                           % (root, '<ObjectList>%s</ObjectList>' % ''.join(items) if items else '', root))


def overview():
    return export_document('<Hmi.Screen.ScreenOverview ID="0"><AttributeList><Height>60</Height></AttributeList>'
                           '</Hmi.Screen.ScreenOverview>')


class SlideinGlobalRuleTest(unittest.TestCase):
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)

    def found(self, files, for_import=True, prefixes=('slidein.', 'globalscreen.', 'handbuilt.')):
        for rel, text in files.items():
            self.repo.write(rel, text)
        return [(f.severity, f.document, f.object, f.rule)
                for f in validate(self.repo.path, for_import=for_import) if f.rule.startswith(prefixes)]

    def test_exports_pass(self):
        self.assertEqual([], self.found({'hmi/slideins/Top.xml': slidein(),
                                         'hmi/global/ScreenGlobalElements.xml': global_elements(),
                                         'hmi/global/ScreenOverview.xml': overview()}))

    def test_global_elements_holding_a_screen_item_are_refused(self):
        rel = 'hmi/global/ScreenGlobalElements.xml'
        self.assertEqual([('error', rel, 'Text_1', 'globalscreen.screen-item')],
                         self.found({rel: global_elements([rect('Text_1')])}))
        message = [f.message for f in validate(self.repo.path, for_import=True) if f.rule == 'globalscreen.screen-item'][0]
        self.assertIn('not allowed in screen Global screen', message)
        self.assertIn('ended', message)

    def test_the_preview_reports_the_screen_item_too(self):
        rel = 'hmi/global/ScreenGlobalElements.xml'
        self.assertEqual([('error', rel, 'Text_1', 'globalscreen.screen-item')],
                         self.found({rel: global_elements([rect('Text_1')])}, for_import=False))

    def test_another_object_in_the_slideins_folder_is_refused(self):
        self.assertEqual([('error', 'hmi/slideins/Top.xml', None, 'slidein.not-slidein')],
                         self.found({'hmi/slideins/Top.xml': slidein(root='Hmi.Screen.Screen')}))

    def test_another_object_in_the_global_folder_is_refused(self):
        self.assertEqual([('error', 'hmi/global/Main.xml', None, 'globalscreen.not-global')],
                         self.found({'hmi/global/Main.xml': slidein(root='Hmi.Screen.Screen')}))

    def test_a_slidein_listed_as_handbuilt_is_not_imported_over(self):
        self.repo.handbuilt([{'screen': 'Top', 'kind': 'alarm view', 'x': 0, 'y': 0, 'w': 100, 'h': 100}])
        self.assertEqual([('error', 'hmi/slideins/Top.xml', None, 'handbuilt.override')],
                         self.found({'hmi/slideins/Top.xml': slidein(), 'hmi/slideins/Left.xml': slidein('Left')}))
        message = [f.message for f in validate(self.repo.path, for_import=True) if f.rule == 'handbuilt.override'][0]
        self.assertIn('alarm view', message)
        self.assertIn('Slide-in Top', message)

    def test_a_slidein_is_named_by_its_edge_whatever_its_file(self):
        self.repo.handbuilt([{'screen': 'Left', 'kind': 'alarm view', 'x': 0, 'y': 0, 'w': 100, 'h': 100}])
        self.assertEqual([('error', 'hmi/slideins/Top.xml', None, 'handbuilt.override')],
                         self.found({'hmi/slideins/Top.xml': slidein('Left')}))

    def test_global_elements_listed_as_handbuilt_are_not_imported_over(self):
        self.repo.handbuilt([{'screen': 'ScreenGlobalElements', 'kind': 'alarm window', 'x': 0, 'y': 0, 'w': 1, 'h': 1}])
        self.assertEqual([('error', 'hmi/global/ScreenGlobalElements.xml', None, 'handbuilt.override')],
                         self.found({'hmi/global/ScreenGlobalElements.xml': global_elements(),
                                     'hmi/global/ScreenOverview.xml': overview()}))

    def test_the_preview_does_not_report_a_handbuilt_export(self):
        # the export is TIA's own: only an import of it would drop the hand-built objects
        self.repo.handbuilt([{'screen': 'Top', 'kind': 'alarm view', 'x': 0, 'y': 0, 'w': 100, 'h': 100}])
        self.assertEqual([], self.found({'hmi/slideins/Top.xml': slidein()}, for_import=False))

    def test_the_documents_of_the_device_given(self):
        self.repo.write('hmi/HMI_A/global/ScreenGlobalElements.xml', global_elements([rect('Text_1')]))
        self.repo.write('hmi/HMI_B/global/ScreenGlobalElements.xml', global_elements([rect('Text_2')]))
        self.assertEqual([('error', 'hmi/HMI_B/global/ScreenGlobalElements.xml', 'Text_2', 'globalscreen.screen-item')],
                         [(f.severity, f.document, f.object, f.rule)
                          for f in validate(self.repo.path, for_import=True, device='HMI_B')
                          if f.rule.startswith('globalscreen.')])


if __name__ == '__main__':
    unittest.main()
