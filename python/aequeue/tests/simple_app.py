from math import floor
from random import uniform
import xml.etree.ElementTree as xmlElementTree

from ..vendor.Qt import QtWidgets, QtCore

from .. import const, resources
from ..widgets import Window
from ..options import RenderOptions


def clamp(value, mn, mx):
    return min(max(value, mn), mx)


def fit(value, omin, omax, nmin, nmax):
    nvalue = (((value - omin) * (nmax - nmin)) / (omax - omin)) + nmin
    return clamp(nvalue, nmin, nmax)


def fit100(value, mn, mx):
    return fit(value, mn, mx, 0, 100)


def percent_to_status(percent, statuses):
    index = int(floor((percent / 100.0) * (len(statuses) - 1)))
    return statuses[index]


def statuses_for_options(options):
    check_statuses = [
        (bool(False), const.Queued),
        (bool(options.module), const.Rendering),
        (bool(options.mp4), const.Encoding),
        (bool(options.gif), const.Encoding),
        (bool(const.Copying), const.Copying),
        (bool(options.sg), const.Uploading),
        (bool(const.Done), const.Done),
    ]
    return [status for has_status, status in check_statuses if has_status]


class MockRenderPipeline(QtCore.QObject):

    status_changed = QtCore.Signal(str)
    item_status_changed = QtCore.Signal([str, str, int])
    done = QtCore.Signal()
    interval = 50

    def __init__(self, items, options, parent=None):
        super(MockRenderPipeline, self).__init__(parent)
        self.statuses = statuses_for_options(options)
        self.items = items
        self.options = options
        self.states = {
            item: {
                'start': int(uniform(1, 20)),
                'duration': int(uniform(100, 200)),
                'status': 'queued',
                'percent': 0,
            } for item in self.items
        }
        self._time = 0
        self._timer = None
        self._done = False
        self.set_status(const.Waiting)

    def __call__(self):
        self._time += 1
        unfinished_items = []
        for item in self.items:
            state = self.states[item]
            state['percent'] = fit100(
                self._time,
                state['start'],
                state['start'] + state['duration'],
            )
            state['status'] = percent_to_status(
                state['percent'],
                self.statuses,
            )
            self.item_status_changed.emit(
                item, state['status'], state['percent']
            )
            if state['status'] != const.Done:
                unfinished_items.append(item)

        if not unfinished_items:
            self._done = True
            self.done.emit()

    def set_status(self, status):
        self.status = status
        self.status_changed.emit(status)

    def run(self):
        if self._timer and self._timer.isActive():
            return

        # Create QTimer
        # Simulates multiple items executing and emits their changing statuses
        self._timer = None
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.interval)
        self._timer.timeout.connect(self)
        self.done.connect(self._timer.stop)
        self.done.connect(lambda: self.set_status(const.Success))

        # Start Timer
        self._timer.start()
        self.set_status(const.Running)


class TestApplication(QtCore.QObject):

    def __init__(self, nitems, parent=None):
        super(TestApplication, self).__init__(parent)

        self.items = ['Comp {:0>2d}'.format(i) for i in range(nitems)]
        self.pipeline = None

        # Create UI
        self.ui = Window()
        self.ui.queue_button.clicked.connect(self.load_queue)
        self.ui.queue.drag.connect(self.drag_queue)
        self.ui.queue.drop.connect(self.drop_queue)
        self.ui.render.clicked.connect(self.render)

    def show(self):
        self.ui.show()

    def drag_queue(self, event):
        data = {
            'action': event.proposedAction(),
            'formats': event.mimeData().formats(),
            'hasColor': event.mimeData().hasColor(),
            'hasHtml': event.mimeData().hasHtml(),
            'hasImage': event.mimeData().hasImage(),
            'hasText': event.mimeData().hasText(),
            'hasUrls': event.mimeData().hasUrls(),
            'html': event.mimeData().html(),
            'text': event.mimeData().text(),
            'color': event.mimeData().colorData(),
            'imageData': event.mimeData().imageData(),
            'urls': event.mimeData().urls(),
        }
        format_data = {
            format: event.mimeData().data(format).data().decode('utf-8', 'ignore')
            for format in event.mimeData().formats()
        }
        print('Received drag event...\n')
        print('\n'.join([f'{k}: {v}' for k, v in data.items()]))
        print('\n'.join([f'{k}: {v}' for k, v in format_data.items()]))
        print('HAS AE DYNAMIC LINKS: %s' % has_dynamic_links(event.mimeData()))
        print('LINKS: %s' % get_dynamic_links(event.mimeData()))
        event.acceptProposedAction()

    def drop_queue(self, event):
        dynamic_links = get_dynamic_links(event.mimeData())
        for link in dynamic_links:
            self.ui.queue.add_item(link['ID'])
        event.acceptProposedAction()

    def load_queue(self):
        self.ui.queue.clear()
        for item in self.items:
            self.ui.queue.add_item(item, const.Queued, 0)
        self.set_render_status(const.Waiting)

    def render(self):
        # Create and connect render pipeline
        self.pipeline = MockRenderPipeline(
            items=self.items,
            options=RenderOptions(**self.ui.options.get()),
            parent=self,
        )
        self.pipeline.item_status_changed.connect(self.ui.queue.update_item)
        self.pipeline.status_changed.connect(self.set_render_status)

        # Simulate Render Pipeline
        self.pipeline.run()

    def set_render_status(self, status):
        if status == const.Waiting:
            self.ui.options_header.label.setText('OPTIONS')
            self.ui.options.setEnabled(True)
            self.ui.render.setEnabled(True)
            self.ui.queue_button.setVisible(True)

            self.ui.render.enable_movie(False)
            self.ui.render.set_height(36)
        if status == const.Running:
            self.ui.options_header.label.setText('STATUS')
            self.ui.options.setEnabled(False)
            self.ui.render.setEnabled(False)
            self.ui.queue_button.setVisible(False)

            movie = resources.get_path(const.Running.title() + '.gif')
            self.ui.render.set_movie(movie)
            self.ui.render.enable_movie(True)
            self.ui.render.set_height(
                self.ui.options_header.height()
                + self.ui.options.height()
            )
        if status in [const.Failed, const.Success]:
            self.ui.options_header.label.setText('STATUS')
            self.ui.options.setEnabled(False)
            self.ui.render.setEnabled(False)
            self.ui.queue_button.setVisible(True)

            movie = resources.get_path(status.title() + '.gif')
            self.ui.render.add_movie_to_queue(movie)


ae_mime_format = 'application/x-qt-windows-mime;value="dynamiclinksourcelist"'

def has_dynamic_links(mimeData):
    return mimeData.hasFormat(ae_mime_format)

def get_dynamic_links(mimeData):
    dynamic_links_data = mimeData.data(ae_mime_format).data()
    dynamic_links = dynamic_links_data.decode('utf-8', 'ignore')
    results = []
    tree = xmlElementTree.fromstring(dynamic_links)
    for source in tree.findall('.//Source'):
        link = {}
        for child in source:
            link[child.tag] = child.text
        results.append(link)
    return results
