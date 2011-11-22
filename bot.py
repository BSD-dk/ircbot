#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: set sw=4 sts=4 et tw=120 :

# Copyright (c) 2011 Alexander Færøy <ahf@0x90.dk>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from __future__ import with_statement

import sys

import simplejson as json

from fnmatch import fnmatch
from collections import deque

from twisted.words.protocols import irc
from twisted.internet import protocol, reactor, ssl

class ChannelState(object):
    def __init__(self, name):
        self.name = name
        self.opped = False

    def getName(self):
        return self.name

    def isOpped(self):
        return self.opped

    def setOpped(self, v):
        self.opped = v

class Hostmask(object):
    def __init__(self, nickname, username, hostname):
        self.nickname = nickname
        self.username = username
        self.hostname = hostname

    def getNickname(self):
        return self.nickname

    def getUsername(self):
        return self.username

    def getHostname(self):
        return self.hostname

    def getHostmask(self):
        return str(self)

    def __str__(self):
        return "%s!%s@%s" % (self.nickname, self.username, self.hostname)

    @staticmethod
    def parse(hostmask):
        tmp = hostmask.split('@')
        if len(tmp) != 2:
            return None

        hostname = tmp[1]

        tmp = tmp[0].split('!')
        if len(tmp) != 2:
            return None

        nickname = tmp[0]
        username = tmp[1]

        return Hostmask(nickname, username, hostname)

class Channel(object):
    def __init__(self, name, operators):
        self.name = name
        self.operators = operators

    def getName(self):
        return self.name

    def getOperators(self):
        return self.operators

    def __repr__(self):
        return self.name

class User(object):
    def __init__(self, name, mask, userclass):
        self.name = name
        self.mask = mask
        self.userClass = userclass

    def getName(self):
        return self.name

    def getUserClass(self):
        return self.userClass

    def getMask(self):
        return self.mask

    def match(self, other):
        return fnmatch(other, self.mask)

    def __repr__(self):
        return self.name

class Server(object):
    def __init__(self, hostname, port, ssl):
        self.hostname = hostname
        self.port = port
        self.ssl = ssl

    def getHostname(self):
        return self.hostname

    def getPort(self):
        return self.port

    def isSecure(self):
        return self.ssl

    def __repr__(self):
        return self.hostname

class UserRegistry(object):
    def __init__(self):
        self.users = {}

    def registerUser(self, user):
        self.users[user.getName()] = user

    def find(self, username):
        return self.users.get(username)

    def contains(self, username):
        return username in self.users

    def getUsers(self):
        return self.users.values()

    def findMatches(self, hostmask):
        r = []

        for _, user in self.users.items():
            if user.match(hostmask.getHostmask()):
                r.append(user)

        return r

class Configuration(object):
    def __init__(self):
        self.nickname = ""
        self.username = ""
        self.realname = ""
        self.servers = deque()
        self.channels = set()
        self.userRegistry = UserRegistry()
        self.currentServer = None

        # Errors and warnings.
        self.valid = True
        self.errorMessages = []
        self.warningMessages = []

    def invalidate(self):
        self.valid = False

    def isValid(self):
        return self.valid

    def hasUser(self, username):
        return self.userRegistry.contains(username)

    def findUser(self, username):
        return self.userRegistry.find(username)

    def setNickname(self, nickname):
        self.nickname = nickname

    def getNickname(self):
        return self.nickname

    def setUsername(self, username):
        self.username = username

    def getUsername(self):
        return self.username

    def setRealname(self, realname):
        self.realname = realname

    def getRealname(self):
        return self.realname

    def appendErrorMessage(self, errorMessage):
        self.errorMessages.append(errorMessage)

    def getErrorMessages(self):
        return self.errorMessages

    def appendWarningMessage(self, warningMessage):
        self.warningMessages.append(warningMessage)

    def getWarningMessages(self):
        return self.warningMessages

    def addUser(self, user):
        self.userRegistry.registerUser(user)

    def getUsers(self):
        return self.userRegistry.getUsers()

    def addServer(self, server):
        self.servers.append(server)

    def getServers(self):
        return self.servers

    def addChannel(self, channel):
        self.channels.add(channel)

    def getChannels(self):
        return self.channels

    def getChannel(self, channel):
        # FIXME: O(n) for something that should have been O(log n). Oh, well...  self.channels should have been a
        # dictonary with a mapping between channel-name and matching Channel-object instance.  Fixing this would require
        # a minor change in the configuration encoder and decoder.
        for c in self.channels:
            if channel == c.getName():
                return c

        return None

class ConfigurationEncoder(json.JSONEncoder):
    def default(self, config):
        if isinstance(config, Configuration):
            data = {
                "bot": {},
                "servers": [],
                "users": [],
                "channels": []
            }

            data["bot"]["nickname"] = config.getNickname()
            data["bot"]["username"] = config.getUsername()
            data["bot"]["realname"] = config.getRealname()

            for s in config.getServers():
                data["servers"].append({
                    "hostname": s.getHostname(),
                    "port": s.getPort(),
                    "ssl": s.isSecure()
                })

            for u in config.getUsers():
                data["users"].append({
                    "name": u.getName(),
                    "mask": u.getMask(),
                    "class": u.getUserClass()
                })

            for c in config.getChannels():
                data["channels"].append({
                    "name": c.getName(),
                    "operators": [o.getName() for o in c.getOperators()]
                })

            return data

        return json.JSONEncoder(self, obj)

class ConfigurationDecoder(object):
    required_keys = set(["bot", "servers", "users", "channels"])
    valid_user_classes = set(["admin", "user"])
    invalid_user_masks = set(["*", "*@*", "*!*", "*!*@*"])

    def decode(self, obj):
        config = Configuration()

        # Sanity check.
        for key in self.required_keys:
            if key not in obj:
                config.appendErrorMessage("Configuration file lacks '%s' key." % key)
                config.invalidate()

        # If our configuration file is invalid at this point, there is no need
        # for us to continue inspecting the configuration file, so we simply
        # return an invalid Configuration object to the caller which then can
        # notify the user about what is wrong and revert to its current
        # configuration file or exit if there is no configuration file to revert
        # back to.
        if not config.isValid():
            return config

        if "nickname" not in obj["bot"]:
            config.appendErrorMessage("Missing nickname.")
            config.invalidate()

        if "username" not in obj["bot"]:
            config.appendErrorMessage("Missing username.")
            config.invalidate()

        if "realname" not in obj["bot"]:
            config.appendErrorMessage("Missing realname")
            config.invalidate()

        # Again, if our configuration file is invalid at this point, we might as
        # well return an invalid configuration now.
        if not config.isValid():
            return config

        # We have already checked for these:
        config.setNickname(obj["bot"]["nickname"])
        config.setUsername(obj["bot"]["username"])
        config.setRealname(obj["bot"]["realname"])

        # The only required key for a server is the port. We default to port
        # 6667 and non-SSL if none of those keys are present.
        for s in obj["servers"]:
            if "hostname" not in s:
                config.appendWarningMessage("Ignored server-entry due to lack of hostname.")
                continue

            hostname = s["hostname"]
            port = 6667
            ssl = False

            if "port" in s:
                port = s["port"]

            if "ssl" in s:
                if s["ssl"]:
                    ssl = True

            config.addServer(Server(hostname, port, ssl))

        # The only required keys for a user is the name and mask;
        for u in obj["users"]:
            if "name" not in u:
                config.appendWarningMessage("Ignored user-entry due to lack of name.")
                continue

            if "mask" not in u:
                config.appendWarningMessage("Ignored user-entry due to lack of mask.")
                continue

            if u["mask"] in self.invalid_user_masks:
                config.appendWarningMessage("Insecure mask for user '%s'" % u["name"])
                continue

            name = u["name"]
            mask = u["mask"]
            userClass = "user"

            if "class" in u:
                if u["class"] not in self.valid_user_classes:
                    config.appendWarningMessage("Ignoring invalid class '%s'." % u["class"])
                else:
                    userClass = u["class"]

            config.addUser(User(name, mask, userClass))

        # The only required key for a channel is the name itself.
        for c in obj["channels"]:
            if "name" not in c:
                config.appendWarningMessage("Ignored channel-entry due to lack of name.")
                continue

            name = c["name"]
            operators = set([])

            # We are validating usernames here by checking with the
            # configuration object if the user has already been added.
            # Otherwise, we ignore it and emits a warning.
            if "operators" in c:
                for operator in c["operators"]:
                    if not config.hasUser(operator):
                        config.appendWarningMessage("Unknown operator '%s'" % operator)
                        continue

                    # Append the operator to the list of users. Remember the
                    # fact that objects in Python are passed as references.
                    operators.add(config.findUser(operator))

            config.addChannel(Channel(name, operators))

        return config

class ConfigurationLoader(object):
    def load(self, filename):
        decoder = ConfigurationDecoder()
        content = {}

        with open(filename) as f:
            content = json.load(f, encoding = "ASCII")

        return decoder.decode(content)

class ConfigurationSaver(object):
    def save(self, filename, configuration):
        content = json.dumps(configuration, cls = ConfigurationEncoder, indent = 4, sort_keys = True)

        with open(filename, 'w') as f:
            f.write(content + '\n')

class ConfigurationService(object):
    def __init__(self, filename):
        # This should only happen when the bot is initially run. In case there
        # is an error here, we must shut down since there is no configuration
        # file to revert back to.
        loader = ConfigurationLoader()
        self.filename = filename
        self.config = loader.load(filename)
        self.currentServer = None
        self.channelStates = {}

        for warning in self.config.getWarningMessages():
            print "   * %s (Warning)" % warning

        if not self.config.isValid():
            print "Errors and/or warnings was found whilst trying to load the configuration file:"

            for error in self.config.getErrorMessages():
                print "   * %s (Error)" % error

            sys.exit(1)

    def reload(self):
        loader = ConfigurationLoader()
        config = loader.load(self.filename)

        # FIXME: Refactor this code into a sanityCheck(self, config) method.
        if not config.isValid():
            # FIXME: Warn the user who is trying to reload that the reload failed.
            return

        # FIXME: Make sure that if, for example, the nickname has changed that
        # we sent a NICK newnick to the server.
        # merge()

        self.config = config

    def save(self):
        saver + ConfigurationSaver()
        saver.save(self.filename, self.config)

    def getChannels(self):
        return self.config.getChannels()

    def getNickname(self):
        return self.config.getNickname()

    def getUsername(self):
        return self.config.getUsername()

    def getRealname(self):
        return self.config.getRealname()

    def findMatches(self, hostmask):
        return self.config.userRegistry.findMatches(hostmask)

    def nextServer(self):
        servers = self.config.getServers()
        self.currentServer = servers.popleft()
        servers.append(self.currentServer)

        return self.currentServer

    def getChannelState(self, channel):
        return self.channelStates.get(channel)

    def joinedChannel(self, channel):
        self.channelStates[channel] = ChannelState(channel)

    def partedChannel(self, channel):
        del self.channelStates[channel]

    def findOperatorCandidates(self, hostmask, channel):
        c = self.config.getChannel(channel)
        r = []

        # In this case, we are currently in a channel that is not listed in our configuration file. This could possibly
        # be due to forced channel join by an operator. This is only possible on certain dodgy IRCd's, like unreal and
        # friends, where operators have more power than God himself.
        if c == None:
            return r

        for operator in c.getOperators():
            if operator.match(hostmask.getHostmask()):
                r.append(operator)

        return r

class Client(irc.IRCClient):
    def _getConfig(self):
        return self.factory.config

    def _getNickname(self):
        return self.config.getNickname()

    def _getUsername(self):
        return self.config.getUsername()

    def _getRealname(self):
        return self.config.getRealname()

    config = property(_getConfig)
    nickname = property(_getNickname)
    username = property(_getUsername)
    realname = property(_getRealname)

    def alterCollidedNick(self, nickname):
        return nickname + "_"

    def signedOn(self):
        print ">>> Signed On"

        for channel in self.config.getChannels():
            self.join(channel.getName())

    def joined(self, channel):
        print ">>> Joining: %s" % channel
        self.config.joinedChannel(channel)

    def userJoined(self, user, channel):
        print ">>> %s has joined %s" % (user, channel)

    def privmsg(self, user, target, message):
        if self.nickname != target:
            return

        hostmask = Hostmask.parse(user)

        if hostmask is None:
            return

        print ">>> Message from '%s': '%s'" % (hostmask.getHostmask(), message)

        parameters = message.split(" ")
        length = len(parameters)

        if length >= 1:
            method = getattr(self, "cmd_%s" % parameters[0], None)

            if method:
                print ">>> Executing handler for command '%s'" % parameters[0]
                method(hostmask, parameters)
            else:
                self.notice(hostmask.getNickname(), "Unknown Command: %s" % message)

    def irc_JOIN(self, prefix, params):
        assert len(params) == 1

        hostmask = Hostmask.parse(prefix)
        channel = params[0]
        nickname = hostmask.getNickname()

        # Default implementation from Twisted:
        if nickname == self.nickname:
            self.joined(channel)
        else:
            self.userJoined(nickname, channel)
            self.considerOpping(hostmask, channel)

    def op(self, channel, nick):
        self.mode(channel, True, "o", user = nick)

    def ctcpUnknownQuery(self, user, channel, tag, data):
        # Ignore unknown CTCP messages.
        pass

    def ctcpQuery_OP(self, user, target, message):
        if target != self.nickname:
            return

        if message is None:
            return

        hostmask = Hostmask.parse(user)

        if hostmask is None:
            return

        channels = message.split(" ")
        message = ", ".join(channels)

        print ">>> CTCP OP from '%s' for channels: %s" % (hostmask.getHostmask(), message)

        for channel in channels:
            self.considerOpping(hostmask, channel)

    def considerOpping(self, hostmask, channel):
        cs = self.config.getChannelState(channel)

        if not cs:
            return

        if not cs.isOpped():
            return

        print ">>> Considering giving op to %s on %s" % (hostmask.getNickname(), channel)
        matches = self.config.findOperatorCandidates(hostmask, channel)

        nick = hostmask.getNickname()
        op = False

        for match in matches:
            print ">>> Found match for %s: '%s' matched '%s' for bot user '%s'" % (nick, hostmask.getHostmask(), match.getMask(), match.getName())
            op = True

        if op:
            self.op(channel, nick)

    def userLeft(self, user, channel):
        print ">>> %s has left %s" % (user, channel)

    def userQuit(self, user, quitMessage):
        print ">>> %s has quit: %s" % (user, quitMessage)

    def userKicked(self, kickee, channel, kicker, message):
        print ">>> %s got kicked by %s on %s: %s" % (kickee, kicker, channel, message)

    def kickedFrom(self, channel, kicker, message):
        print ">>> %s kicked us from %s: %s" % (kicker, channel, message)
        self.config.partedChannel(channel)
        self.join(channel)

    def modeChanged(self, user, channel, added, modes, args):
        hostmask = Hostmask.parse(user)

        if hostmask == None:
            modeChanger = user
        else:
            modeChanger = hostmask.getNickname()

        if added:
            c = '+'
        else:
            c = '-'

        # Icky.
        if not args or not args[0]:
            print ">>> Mode/%s [%c%s] by %s" % (channel, c, modes, modeChanger)
        else:
            print ">>> Mode/%s [%c%s %s] by %s" % (channel, c, modes, ' '.join(args), modeChanger)

        # Only check for operator mode change.
        pairedModes = zip(modes, args)

        for mode in pairedModes:
            modeChar = mode[0]
            target = mode[1]

            if modeChar == 'o':
                if added:
                    self.userOpped(user, target, channel)
                else:
                    self.userDeopped(user, target, channel)

    def userOpped(self, user, target, channel):
        # We got opped.
        if self.nickname == target:
            cs = self.config.getChannelState(channel)

            if not cs:
                return

            cs.setOpped(True)

    def userDeopped(self, user, target, channel):
        # We got deopped.
        if self.nickname == target:
            cs = self.config.getChannelState(channel)

            if not cs:
                return

            cs.setOpped(False)

    def cmd_whoami(self, hostmask, parameters):
        users = self.config.findMatches(hostmask)
        target = hostmask.getNickname()

        if users:
            for user in users:
                self.notice(target, "Username: '%s'" % user.getName())
                self.notice(target, "Hostmask: '%s'" % user.getMask())
                self.notice(target, "Class:    '%s'" % user.getUserClass())
        else:
            self.notice(target, "Unknown user")

class ClientFactory(protocol.ClientFactory):
    protocol = Client

    def __init__(self, config):
        self.config = config

    def startedConnecting(self, connector):
        destination = connector.getDestination()
        print ">>> Connecting to: %s:%d" % (destination.host, destination.port)

    def clientConnectionLost(self, connector, reason):
        print ">>> Connection Lost: %s" % reason.getErrorMessage()
        print ">>> Reconnecting"

        # FIXME: Handle server switch here.
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        print ">>> Connection Failed: %s" % reason.getErrorMessage()
        print ">>> Reconnecting"

class Bot(object):
    def __init__(self, filename):
        config = ConfigurationService(filename)
        server = config.nextServer()
        clientFactory = ClientFactory(config)

        if server.isSecure():
            reactor.connectSSL(server.getHostname(), server.getPort(), clientFactory, ssl.ClientContextFactory())
        else:
            reactor.connectTCP(server.getHostname(), server.getPort(), clientFactory)

    def runForever(self):
        reactor.run()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print "Usage: %s path/to/config.json" % sys.argv[0]
        sys.exit(1)

    bot = Bot(sys.argv[1])
    bot.runForever()
