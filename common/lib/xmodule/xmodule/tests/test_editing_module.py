# -*- coding: utf-8 -*-

import unittest
import os
import logging

from mock import Mock
from pkg_resources import resource_string
from xmodule.videoalpha_module import VideoAlphaDescriptor

from .import get_test_system

log = logging.getLogger(__name__)


class TabsEditingDescriptorTestCase(unittest.TestCase):
    """ Testing TabsEditingDescriptor"""

    def setUp(self):
        super(TabsEditingDescriptorTestCase, self).setUp()
        system = get_test_system()
        system.render_template = Mock(return_value="<div>Test Template HTML</div>")
        self.tabs = [
            {
                'name': "Test_css",
                'template': "tabs/codemirror-edit.html",
                'current': True,
                'css': {'scss': [resource_string(__name__,
                '../../test_files/test_tabseditingdescriptor.scss')]}
            },
            {
                'name': "Subtitles",
                'template': "videoalpha/subtitles.html",
            },
            {
                'name': "Settings",  # Do not rename settings tab.
                'template': "tabs/metadata-edit-tab.html"
            }
        ]
        VideoAlphaDescriptor.tabs = self.tabs
        VideoAlphaDescriptor.hide_settings = True
        self.descriptor = VideoAlphaDescriptor(
            runtime=system,
            model_data={})

    def test_get_css(self):
        """test get_css"""
        css = self.descriptor.get_css()
        test_files_dir = os.path.dirname(__file__).replace('xmodule/tests', 'test_files')
        test_css_file = os.path.join(test_files_dir, 'test_tabseditingdescriptor.scss')
        with open(test_css_file) as new_css:
            added_css = new_css.read()
        self.assertEqual(css['scss'].pop(), added_css)

    def test_get_context(self):
        """"test get_context"""
        rendered_context = self.descriptor.get_context()
        self.assertEqual(rendered_context['hide_settings'], True)
        self.assertListEqual(rendered_context['tabs'], self.tabs)
