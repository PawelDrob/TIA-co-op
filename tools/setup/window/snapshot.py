"""--snap: the window with no one at it, transparent on the screen: a picture of what opens, of each page, of the menu
and of a page opened from it, then it ends. With changes, it presses each button that changes something and pictures the
outcome. Writes done.txt last, with the outcome of each press, so a check knows it ended."""
import os

from TiaArchiveCompare.window.snapshot import screenshot
from tools.setup.window import model

POLL_MS = 100
PRESSED_ON = ('repository', 'bridge', 'viewer', 'dashboards')


class Snapshot:
    def __init__(self, window, folder, changes):
        self.window, self.folder, self.changes = window, folder, changes
        self.log = []
        self.pressed = set()

    def run(self):
        os.makedirs(self.folder, exist_ok=True)
        w = self.window
        w.attributes('-alpha', 0)
        w.maxsize(4000, 4000)       # Tk holds a window to the screen: the shots have the same size on any screen
        w.geometry('%dx%d' % (w.px(900), w.px(680)))
        self.plan = [('opens', w.page, '0-opens')]      # what a double-click opens: the first page, or the menu after Finish
        for i, (key, _, _) in enumerate(model.PAGES):
            self.plan.append(('page', i, f'{i + 1}-{key}'))
            if self.changes and key in PRESSED_ON:
                self.plan.append(('press', i, f'{i + 1}-{key}-done'))
        self.plan += [('menu', None, f'{len(model.PAGES) + 1}-menu'),
                      ('from menu', model.page_index('bridge'), f'{len(model.PAGES) + 2}-bridge-from-the-menu')]
        w.after(POLL_MS, self._next)
        w.mainloop()
        self.log += [f'{key}: {"failed" if failed else "ok"}: {text}' for key, (failed, text) in w.details.items()]
        with open(os.path.join(self.folder, 'done.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(self.log) + '\n')
        return 0

    def _idle(self):
        return not self.window.busy and self.window.look is not None

    def _next(self):
        w = self.window
        if not self._idle():
            return w.after(POLL_MS, self._next)
        if not self.plan:
            return w.destroy()
        what, page, name = self.plan[0]
        if what == 'press' and self._press(page):
            return w.after(POLL_MS, self._next)      # one more button: the next round sees its outcome
        self.plan.pop(0)
        if what == 'menu':
            w.finish()
        elif what == 'opens':
            self.log.append('opens ' + ('the menu' if page is None else f'page {page + 1}'))
        elif w.page != page:
            w.go(page)
        w.update()
        screenshot(w, os.path.join(self.folder, name + '.png'))
        w.after(POLL_MS, self._next)

    def _press(self, page):
        """Presses the next button of the page that changes something and was not pressed yet; False when none is left.
        A dashboard is started, never opened: that would open a browser."""
        w = self.window
        if w.page != page:
            w.go(page)
        key = model.PAGES[page][0]
        look = w.page_look() if key == 'bridge' else w.look
        for row in model.page_rows(look, key):
            for action in row.actions:
                if action.kind in ('make', 'register', 'start') and (row.key, action.kind) not in self.pressed:
                    self.pressed.add((row.key, action.kind))
                    self.log.append(f'pressed {action.label} on {row.title}')
                    w.act(row, action)
                    return True
        return False
