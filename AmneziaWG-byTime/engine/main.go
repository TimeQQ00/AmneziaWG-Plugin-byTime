// awgcore - userspace AmneziaWG engine for the exteraGram plugin.
// Plugin: "AmneziaWG byTime" - made by Time.
//
// awgcore — userspace AmneziaWG engine for the exteraGram plugin.
//
// Loaded as a c-shared library from Python (ctypes). The engine builds an
// AmneziaWG tunnel entirely in userspace (gVisor netstack — no TUN device,
// no VpnService) and exposes a local SOCKS5 server that routes TCP through
// the tunnel. Telegram is pointed at 127.0.0.1:<socksPort> by the plugin.
//
// C API:
//   int awgStart(const char *configJson)  0 = ok, -1 = bad json, -2 = start error
//   int awgStop(void)                     0 = ok
//   int awgStatus(void)                   1 = running, 0 = idle
package main

/*
#include <stdlib.h>
*/
import "C"

import (
	"context"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/netip"
	"strings"
	"sync"

	"github.com/amnezia-vpn/amneziawg-go/v3/conn"
	"github.com/amnezia-vpn/amneziawg-go/v3/device"
	"github.com/amnezia-vpn/amneziawg-go/v3/tun/netstack"
	"github.com/things-go/go-socks5"
	"github.com/things-go/go-socks5/bufferpool"
)

// awgParamOrder keeps the device-level IPC output deterministic.
var awgParamOrder = []string{
	"jc", "jmin", "jmax", "s1", "s2", "s3", "s4",
	"h1", "h2", "h3", "h4", "i1", "i2", "i3", "i4", "i5",
}

// EngineConfig is the JSON the Python plugin passes to awgStart.
type EngineConfig struct {
	PrivateKey string            `json:"privateKey"`
	Address    []string          `json:"address"`
	DNS        []string          `json:"dns"`
	MTU        int               `json:"mtu"`
	PublicKey  string            `json:"publicKey"`
	Endpoint   string            `json:"endpoint"`
	KeepAlive  int               `json:"keepalive"`
	AllowedIPs []string          `json:"allowedIPs"`
	SocksPort  int               `json:"socksPort"`
	LogLevel   int               `json:"logLevel"`
	AWG        map[string]string `json:"awg"`
}

type engineState struct {
	mu       sync.Mutex
	running  bool
	dev      *device.Device
	listener net.Listener
}

var state engineState

// passthroughResolver is a socks5 NameResolver that performs no resolution:
// it leaves the FQDN untouched (returns a nil IP) so the domain survives to
// the dial callback and is resolved inside the tunnel netstack, whose DNS
// servers came from the config.
type passthroughResolver struct{}

func (passthroughResolver) Resolve(ctx context.Context, name string) (context.Context, net.IP, error) {
	return ctx, nil, nil
}

func b64ToHex(b64 string) (string, error) {
	raw, err := base64.StdEncoding.DecodeString(strings.TrimSpace(b64))
	if err != nil {
		return "", err
	}
	if len(raw) != 32 {
		return "", fmt.Errorf("key must decode to 32 bytes, got %d", len(raw))
	}
	return hex.EncodeToString(raw), nil
}

func parseAddrs(values []string) ([]netip.Addr, error) {
	out := make([]netip.Addr, 0, len(values))
	for _, value := range values {
		addr, err := netip.ParseAddr(strings.TrimSpace(value))
		if err != nil {
			return nil, fmt.Errorf("bad address %q: %w", value, err)
		}
		out = append(out, addr)
	}
	return out, nil
}

func buildIPC(cfg *EngineConfig) (string, error) {
	priv, err := b64ToHex(cfg.PrivateKey)
	if err != nil {
		return "", fmt.Errorf("private key: %w", err)
	}
	pub, err := b64ToHex(cfg.PublicKey)
	if err != nil {
		return "", fmt.Errorf("public key: %w", err)
	}
	var b strings.Builder
	fmt.Fprintf(&b, "private_key=%s\n", priv)

	// Device-level AmneziaWG obfuscation parameters (jc/jmin/jmax/s1..s4/
	// h1..h4/i1..i5) are plain IPC keys understood by amneziawg-go's uapi.
	for _, key := range awgParamOrder {
		if value, ok := cfg.AWG[key]; ok && value != "" {
			fmt.Fprintf(&b, "%s=%s\n", key, value)
		}
	}

	keepalive := cfg.KeepAlive
	if keepalive <= 0 {
		keepalive = 25 // mobile NAT timeouts kill idle tunnels
	}
	fmt.Fprintf(&b, "public_key=%s\n", pub)
	fmt.Fprintf(&b, "preshared_key=%s\n", strings.Repeat("0", 64))
	fmt.Fprintf(&b, "endpoint=%s\n", strings.TrimSpace(cfg.Endpoint))
	fmt.Fprintf(&b, "persistent_keepalive_interval=%d\n", keepalive)
	allowed := cfg.AllowedIPs
	if len(allowed) == 0 {
		allowed = []string{"0.0.0.0/0", "::/0"}
	}
	for _, cidr := range allowed {
		fmt.Fprintf(&b, "allowed_ip=%s\n", strings.TrimSpace(cidr))
	}
	return b.String(), nil
}

func startEngine(cfg *EngineConfig) error {
	localAddresses, err := parseAddrs(cfg.Address)
	if err != nil {
		return err
	}
	dnsServers, err := parseAddrs(cfg.DNS)
	if err != nil {
		return err
	}
	mtu := cfg.MTU
	if mtu <= 0 {
		mtu = 1280
	}

	ipc, err := buildIPC(cfg)
	if err != nil {
		return err
	}

	tunDevice, tnet, err := netstack.CreateNetTUN(localAddresses, dnsServers, mtu)
	if err != nil {
		return err
	}
	dev := device.NewDevice(tunDevice, conn.NewDefaultBind(), device.NewLogger(cfg.LogLevel, "awg"))
	if err := dev.IpcSet(ipc); err != nil {
		dev.Close()
		return err
	}
	if err := dev.Up(); err != nil {
		dev.Close()
		return err
	}

	listener, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", cfg.SocksPort))
	if err != nil {
		dev.Close()
		return err
	}

	server := socks5.NewServer(
		socks5.WithAuthMethods([]socks5.Authenticator{socks5.NoAuthAuthenticator{}}),
		socks5.WithBufferPool(bufferpool.NewPool(256*1024)),
		socks5.WithDial(tnet.DialContext),
		socks5.WithResolver(passthroughResolver{}),
		socks5.WithLogger(socks5.NewLogger(log.New(io.Discard, "", log.LstdFlags))),
	)

	state.dev = dev
	state.listener = listener
	state.running = true

	// Serve blocks until the listener is closed (awgStop); then the state is
	// marked idle. The mutex is free here — awgStart already released it.
	go func() {
		_ = server.Serve(listener)
		state.mu.Lock()
		state.running = false
		state.mu.Unlock()
	}()
	return nil
}

//export awgStart
func awgStart(conf *C.char) C.int {
	state.mu.Lock()
	defer state.mu.Unlock()
	if state.running {
		return 0 // already up
	}
	raw := C.GoString(conf)
	var cfg EngineConfig
	if err := json.Unmarshal([]byte(raw), &cfg); err != nil {
		return -1
	}
	if err := startEngine(&cfg); err != nil {
		log.Printf("awg start failed: %v", err)
		return -2
	}
	return 0
}

//export awgStop
func awgStop() C.int {
	state.mu.Lock()
	defer state.mu.Unlock()
	if !state.running {
		return 0
	}
	if state.listener != nil {
		_ = state.listener.Close()
	}
	if state.dev != nil {
		state.dev.Close()
	}
	state.dev = nil
	state.listener = nil
	state.running = false
	return 0
}

//export awgStatus
func awgStatus() C.int {
	state.mu.Lock()
	defer state.mu.Unlock()
	if state.running {
		return 1
	}
	return 0
}

func main() {}
