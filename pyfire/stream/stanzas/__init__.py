# -*- coding: utf-8 -*-
"""
    pyfire.stream.stanzas
    ~~~~~~~~~~~~~~~~~~~~~~

    Process stream events and redirect to tag handlers

    :copyright: 2011 by the pyfire Team, see AUTHORS for more details.
    :license: BSD, see LICENSE for more details.
"""

import uuid
import xml.etree.ElementTree as ET

import pyfire.configuration as config
from pyfire.jid import JID
<<<<<<< HEAD
from pyfire.services import router, localdomain
=======
from pyfire.stream.stanzas import iq, message, presence
>>>>>>> Drop stanza router, we will use zeromq for that
from pyfire.stream.errors import *


class TagHandler(object):

    def __init__(self, connection):
        super(TagHandler, self).__init__()
        self.connection = connection
        self.send_element = connection.send_element
        self.send_string = connection.send_string

        self.jid = None
        self.hostname = None

        self.authenticated = False

<<<<<<< HEAD
        # create stanza router and register a localdomain service for each domain
        # we serve
        self.service_router = router.Router()
        local_domain_service = localdomain.LocalDomainService()
        for local_domain in config.getlist("listeners", "domains"):
            self.service_router.register_service(local_domain, local_domain_service)
=======
        self.iq = iq.Iq(self)
        self.message = message.Message(self)
        self.presence = presence.Presence(self)
>>>>>>> Drop stanza router, we will use zeromq for that

    def contenthandler(self, tree):
        """Handles an incomming content tree"""

        # set/replace the from attribute in stanzas as required
        # by RFC 6120 Section 8.1.2.1
        if self.authenticated:
            tree.set("from", self.jid)

        try:
            response_element = None
            if tree.tag == "auth":
                registry = self.connection.auth_registry
                namespace = tree.get('xmlns')
                handler = registry.request_handler(namespace)
                handler.process(tree)
                self.connection.parser.reset()
                self.jid = JID("@".join([handler.authenticated_user,
                                         self.hostname]))
                self.authenticated = True
                response_element = ET.Element("success")
                response_element.set("xmlns", namespace)
            else:
                response_element = self.service_router.route_stanza(tree)
                ## extract bind responses to set local, validated jid
                if response_element.find("bind/jid") is not None:
                    self.jid = JID(response_element.find("bind/jid").text)

            if response_element is not None:
                self.send_element(response_element)
        except StreamError, e:
            self.send_string(unicode(e))

    def add_auth_options(self, feature_element):
        """Add supported auth mechanisms to feature element"""
        registry = self.connection.auth_registry

        for mechtype in registry.supported_namespaces:
            mechtype_element = ET.SubElement(feature_element, "mechanisms")
            mechtype_element.set("xmlns", mechtype)
            handler = registry.request_handler(mechtype)
            for mech in handler.supported_mechs:
                mech_element = ET.SubElement(mechtype_element, 'mechanism')
                mech_element.text = mech
            mechanisms = ET.Element("mechanisms")

    def add_server_features(self, feature_element):
        bind = ET.SubElement(feature_element, "bind")
        bind.set("xmlns", "urn:ietf:params:xml:ns:xmpp-bind")

        # Session establishment is deprecated in RFC6121 but Appendix E
        # suggests to still advertise it as feature for compatibility.
        session = ET.SubElement(feature_element, "session")
        session.set("xmlns", "urn:ietf:params:xml:ns:xmpp-session")

    def streamhandler(self, attrs):
        """Handles a stream start"""

        if attrs == {}:
            # </stream:stream> received
            self.connection.stop_connection()
        else:
            # check if we are responsible for this stream
            self.hostname = attrs.getValue("to")
            if self.hostname not in config.getlist("listeners", "domains"):
                raise HostUnknownError

            # Stream restart
            stream = ET.Element("stream:stream")
            stream.set("xmlns", attrs.getValue("xmlns"))
            stream.set("from", self.hostname)
            stream.set("id", uuid.uuid4().hex)
            stream.set("xml:lang", "en")
            stream.set("xmlns:stream", "http://etherx.jabber.org/streams")

            # only include version in response if client sent its max supported
            # version (RFC6120 Section 4.7.5)
            try:
                if attrs.getValue("version") != "1.0":
                    raise UnsupportedVersionError
                stream.set("version", "1.0")
            except KeyError:
                pass

            try:
                from_jid = JID(attrs.getValue("from"))
                stream.set("to", unicode(from_jid))
            except ValueError:
                raise InvalidFromError
            except KeyError:
                pass

            start_stream = """<?xml version="1.0"?>""" + ET.tostring(stream)
            # Element has subitems but are added later to the stream,
            # so don't mark it a single element
            self.send_string(start_stream.replace("/>", ">"))

            # Make a list of supported features
            features = ET.Element("stream:features")
            if not self.authenticated:
                self.add_auth_options(features)
            else:
                self.add_server_features(features)

            self.send_element(features)
