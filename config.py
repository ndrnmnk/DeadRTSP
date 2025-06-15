import yaml

class Config:
    _instance = None

    def __new__(cls, path="config.yaml"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config(path)
        return cls._instance

    def _load_config(self, path):
        with open(path, "r") as file:
            self._config = yaml.safe_load(file)
            self._used_ports = set()

    def get(self, key, default=None):
        return self._config.get(key, default)

    def all(self):
        return self._config

    def port_set_used(self, port):
        print(f"PORT TAKEN: {port}")
        self._used_ports.add(port)

    def port_set_free(self, port):
        print(f"PORT FREED: {port}")
        try:
            self._used_ports.remove(port)
        except KeyError:
            print("PORT DOUBLE FREE")

    def get_free_port(self, mode="udp"):
        # Since all ports allocated through this are used in pairs, only the first port from the pair will be returned
        # Second port can be accessed at returned_port+1
        if mode == "relay":
            start = self._config["min_tcp_relay_port"]
            finish = self._config["max_tcp_relay_port"]
        elif mode == "sdp":
            start = self._config["min_sdp_gen_port"]
            finish = self._config["max_sdp_gen_port"]
        else:
            start = self._config["min_udp_port"]
            finish = self._config["max_udp_port"]

        i = start
        while i < finish:
            if i not in self._used_ports:
                return i
            i += 2
        return None

config_instance = Config()