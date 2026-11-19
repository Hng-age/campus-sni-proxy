import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea
from gui.main_window import MainWindow


class ResponsiveGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_pages_fit_multiple_resolutions_without_horizontal_scroll(self):
        win = MainWindow()
        win.show()
        
        # Test 1024x643 (user screen), 880x560 (small laptop), 1200x760 (standard)
        resolutions = [(1024, 643), (880, 560), (1200, 760)]
        for w, h in resolutions:
            win.resize(w, h)
            self.app.processEvents()
            for idx in range(win.stack.count()):
                win.stack.setCurrentIndex(idx)
                self.app.processEvents()
                page = win.stack.widget(idx)
                name = page.__class__.__name__
                for s in page.findChildren(QScrollArea):
                    h_bar = s.horizontalScrollBar()
                    # Horizontal scrollbar must be disabled/hidden and have zero range
                    self.assertEqual(
                        s.horizontalScrollBarPolicy(),
                        Qt.ScrollBarAlwaysOff,
                        f"Page {name} scrollarea should have ScrollBarAlwaysOff"
                    )
                    self.assertEqual(
                        h_bar.value(), 0,
                        f"Page {name} horizontal scrollbar value shifted to {h_bar.value()}"
                    )
                    # 仅关闭滚动条还不够：range > 0 说明内容被裁切
                    self.assertEqual(
                        h_bar.maximum(), 0,
                        f"Page {name} content is wider than the viewport "
                        f"({h_bar.maximum()} px clipped)"
                    )
        win.close()


if __name__ == "__main__":
    unittest.main()
