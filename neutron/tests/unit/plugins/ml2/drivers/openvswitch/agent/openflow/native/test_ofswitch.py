#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import time
from unittest import mock

import os_ken.exception as os_ken_exc
from os_ken.ofproto import ofproto_v1_3
from os_ken.ofproto import ofproto_v1_3_parser
from oslo_config import cfg

from neutron.plugins.ml2.drivers.openvswitch.agent.openflow.native \
    import ofswitch
from neutron.tests import base


class FakeReply:
    def __init__(self, type):
        self.type = type


class TestBundledOpenFlowBridge(base.BaseTestCase):
    def setUp(self):
        super().setUp()
        br = mock.Mock(spec=['install_instructions', 'foo'])
        br._get_dp = lambda: (mock.Mock(), ofproto_v1_3, ofproto_v1_3_parser)
        br.active_bundles = set()
        self.br = ofswitch.BundledOpenFlowBridge(br, False, False)

    def test_method_calls(self):
        self.br.install_instructions(dummy_arg=1)
        self.br.br.install_instructions.assert_called_once_with(dummy_arg=1)

    def test_illegal_method_calls(self):
        # With python3, this can be written as "with assertRaises..."
        try:
            self.br.uninstall_foo()
            self.fail("Expected an exception")
        except Exception as e:
            self.assertIsInstance(e, AttributeError)
        try:
            self.br.foo()
            self.fail("Expected an exception")
        except Exception as e:
            self.assertIsInstance(e, AttributeError)

    @mock.patch.object(ofswitch.OpenFlowSwitchMixin, '_send_msg_retry')
    def test__send_msg_success(self, mock_send_msg_retry):
        mock_send_msg_retry.return_value = 'xyz'

        app = mock.MagicMock()

        of = ofswitch.OpenFlowSwitchMixin(os_ken_app=app)
        self.assertEqual('xyz', of._send_msg("abc"))

        mock_send_msg_retry.assert_called_once_with("abc", None, False)

    @mock.patch.object(ofswitch.OpenFlowSwitchMixin, '_send_msg_retry')
    def test__send_msg_osken_exc(self, mock_send_msg_retry):

        mock_send_msg_retry.side_effect = os_ken_exc.OSKenException(
            "something wrong!")

        app = mock.MagicMock()

        of = ofswitch.OpenFlowSwitchMixin(os_ken_app=app)
        self.assertRaises(RuntimeError, of._send_msg, "abc")

        self.assertEqual(2, mock_send_msg_retry.call_count)

    @mock.patch.object(ofswitch.OpenFlowSwitchMixin, '_send_msg_retry')
    def test__send_msg_timeout(self, mock_send_msg_retry):
        cfg.CONF.set_override('of_request_timeout', 1, group='OVS')

        mock_send_msg_retry.side_effect = lambda *a, **b: time.sleep(2)

        app = mock.MagicMock()

        of = ofswitch.OpenFlowSwitchMixin(os_ken_app=app)
        self.assertRaises(RuntimeError, of._send_msg, "abc")

        self.assertEqual(2, mock_send_msg_retry.call_count)

    @mock.patch.object(ofswitch.OpenFlowSwitchMixin, '_send_msg_retry')
    def test__send_msg_timeout_invalidates_cached_dpid(self,
                                                       mock_send_msg_retry):
        cfg.CONF.set_override('of_request_timeout', 1, group='OVS')
        mock_send_msg_retry.side_effect = lambda *a, **b: time.sleep(2)

        app = mock.MagicMock()
        of = ofswitch.OpenFlowSwitchMixin(os_ken_app=app)
        of._cached_dpid = 11

        self.assertRaises(RuntimeError, of._send_msg, "abc")
        self.assertIsNone(of._cached_dpid)

    @mock.patch.object(ofswitch.OpenFlowSwitchMixin, '_send_msg_retry')
    def test__send_msg_timeout_recovers_after_single_retry(
            self, mock_send_msg_retry):
        cfg.CONF.set_override('of_request_timeout', 1, group='OVS')

        responses = iter([lambda *a, **b: time.sleep(2), 'xyz'])

        def side_effect(*args, **kwargs):
            response = next(responses)
            if callable(response):
                return response(*args, **kwargs)
            return response

        mock_send_msg_retry.side_effect = side_effect

        app = mock.MagicMock()
        of = ofswitch.OpenFlowSwitchMixin(os_ken_app=app)
        of._cached_dpid = 12

        self.assertEqual('xyz', of._send_msg("abc"))
        self.assertEqual(2, mock_send_msg_retry.call_count)
        self.assertIsNone(of._cached_dpid)

    @mock.patch.object(ofswitch.OpenFlowSwitchMixin, '_send_msg_retry')
    def test__send_msg_timeout_waits_for_dp_before_retry(
            self, mock_send_msg_retry):
        cfg.CONF.set_override('of_request_timeout', 1, group='OVS')

        responses = iter([lambda *a, **b: time.sleep(2), 'xyz'])

        def side_effect(*args, **kwargs):
            response = next(responses)
            if callable(response):
                return response(*args, **kwargs)
            return response

        mock_send_msg_retry.side_effect = side_effect

        app = mock.MagicMock()
        of = ofswitch.OpenFlowSwitchMixin(os_ken_app=app)
        of._cached_dpid = 13
        of._get_dp = mock.Mock(return_value=(mock.Mock(), mock.Mock(),
                                             mock.Mock()))

        self.assertEqual('xyz', of._send_msg("abc"))
        of._get_dp.assert_called_once_with()

    @mock.patch('os_ken.app.ofctl.api.send_msg')
    @mock.patch('os_ken.app.ofctl.api.get_datapath')
    def test__send_msg_retry_replaces_stale_datapath(self, mock_get_dp,
                                                     mock_send_msg):
        app = mock.MagicMock()
        old_dp = mock.Mock(id=10)
        new_dp = mock.Mock(id=10)
        msg = mock.Mock(datapath=old_dp)
        mock_get_dp.return_value = new_dp
        mock_send_msg.return_value = 'xyz'

        of = ofswitch.OpenFlowSwitchMixin(os_ken_app=app)
        self.assertEqual('xyz', of._send_msg_retry(msg, None, False))

        self.assertEqual(new_dp, msg.datapath)
        mock_get_dp.assert_called_once_with(app, 10)
        mock_send_msg.assert_called_once_with(app, msg, None, False)

    def test_normal_bundle_context(self):
        self.assertIsNone(self.br.active_bundle)
        self.br.br._send_msg = mock.Mock(side_effect=[
            FakeReply(ofproto_v1_3.ONF_BCT_OPEN_REPLY),
            FakeReply(ofproto_v1_3.ONF_BCT_COMMIT_REPLY)])
        with self.br:
            self.assertIsNotNone(self.br.active_bundle)
            # Do nothing
        # Assert that the active bundle is gone
        self.assertIsNone(self.br.active_bundle)

    def test_aborted_bundle_context(self):
        self.assertIsNone(self.br.active_bundle)
        self.br.br._send_msg = mock.Mock(side_effect=[
            FakeReply(ofproto_v1_3.ONF_BCT_OPEN_REPLY),
            FakeReply(ofproto_v1_3.ONF_BCT_DISCARD_REPLY)])
        try:
            with self.br:
                self.assertIsNotNone(self.br.active_bundle)
                raise Exception()
        except Exception:
            pass
        # Assert that the active bundle is gone
        self.assertIsNone(self.br.active_bundle)
        self.assertEqual(2, len(self.br.br._send_msg.mock_calls))
        args, kwargs = self.br.br._send_msg.call_args_list[0]
        self.assertEqual(ofproto_v1_3.ONF_BCT_OPEN_REQUEST,
                         args[0].type)
        args, kwargs = self.br.br._send_msg.call_args_list[1]
        self.assertEqual(ofproto_v1_3.ONF_BCT_DISCARD_REQUEST,
                         args[0].type)

    def test_bundle_context_with_error(self):
        self.assertIsNone(self.br.active_bundle)
        self.br.br._send_msg = mock.Mock(side_effect=[
            FakeReply(ofproto_v1_3.ONF_BCT_OPEN_REPLY),
            RuntimeError])
        try:
            with self.br:
                saved_bundle_id = self.br.active_bundle
                self.assertIsNotNone(self.br.active_bundle)
            self.fail("Expected an exception")
        except RuntimeError:
            pass
        # Assert that the active bundle is gone
        self.assertIsNone(self.br.active_bundle)
        self.assertIn(saved_bundle_id, self.br.br.active_bundles)

        self.assertEqual(2, len(self.br.br._send_msg.mock_calls))
        args, kwargs = self.br.br._send_msg.call_args_list[0]
        self.assertEqual(ofproto_v1_3.ONF_BCT_OPEN_REQUEST,
                         args[0].type)
        args, kwargs = self.br.br._send_msg.call_args_list[1]
        self.assertEqual(ofproto_v1_3.ONF_BCT_COMMIT_REQUEST,
                         args[0].type)
