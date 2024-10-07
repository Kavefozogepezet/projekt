
from netsquid.protocols import NodeProtocol

from simlog import log


class ForwardProtocol(NodeProtocol):
    def __init__(self, node, headers, port_map, name=None):
        super().__init__(node, name)
        self.port_map = port_map
        self.headers = headers

    def run(self):
        evexpr = None
        for port in self.port_map:
            _port = self.node.ports[port]
            ev = self.await_port_input(_port)
            if evexpr:
                evexpr = ev
            else:
                evexpr = evexpr & ev

        yield evexpr
        for port_in, port_out in self.port_map.items():
            for header in self.headers:
                msg = self.node.ports[port_in].rx_input(header)
                if msg:
                    log.info(log.msg2str(msg), into=self)
                    self.node.ports[port_out].tx_output(msg)
                    log.info(log.msg2str(msg), outof=self)
