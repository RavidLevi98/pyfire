# -*- coding: utf-8 -*-
"""
    pyfire.stream.stanzas.presence
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    This module handles XMPP presence packets
    as defined in RFC 6121 Section 4.7

    :copyright: 2011 by the pyfire Team, see AUTHORS for more details.
    :license: BSD, see LICENSE for more details.
"""

from base64 import b64decode
from xml.etree.ElementTree import Element, tostring


class Presence(object):
    """This Class handles <resence> XMPP frames"""

    def __init__(self):
        super(Presence, self).__init__()

    def handle(self, tree):
        """handler for resence requests,
           returns a response that should be sent back"""
        response = Element("presence")
        response.set('to', tree.get('from'))
        return response
