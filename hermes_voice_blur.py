"""Blur de fundo com forma exata para uma janela GTK4 (ext-background-effect-v1).

O niri desfoca o fundo de uma layer surface na região que o cliente pede pelo
protocolo; por regra de layer, só daria o retângulo inteiro da superfície. O
GTK não expõe o protocolo, então ele é falado direto na libwayland-client, com
uma fila própria para não disputar a fila do GDK.

Uso: d = Desfoque(janela); d.aplicar([(x, y, w, h), ...]) a cada mudança de
forma; d.aplicar(None) tira o efeito. Falhas viram d.ok = False e nada mais.
"""
from __future__ import annotations

import ctypes as C

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk  # noqa: E402


class _Msg(C.Structure):
    _fields_ = [("name", C.c_char_p), ("signature", C.c_char_p), ("types", C.POINTER(C.c_void_p))]


class _Iface(C.Structure):
    pass


_Iface._fields_ = [("name", C.c_char_p), ("version", C.c_int),
                   ("method_count", C.c_int), ("methods", C.POINTER(_Msg)),
                   ("event_count", C.c_int), ("events", C.POINTER(_Msg))]

_wl = C.CDLL("libwayland-client.so.0")
_gtk = C.CDLL("libgtk-4.so.1")
for nome, res, args in (
    ("wl_display_create_queue", C.c_void_p, [C.c_void_p]),
    ("wl_proxy_create_wrapper", C.c_void_p, [C.c_void_p]),
    ("wl_proxy_wrapper_destroy", None, [C.c_void_p]),
    ("wl_proxy_set_queue", None, [C.c_void_p, C.c_void_p]),
    ("wl_proxy_get_version", C.c_uint32, [C.c_void_p]),
    ("wl_proxy_add_listener", C.c_int, [C.c_void_p, C.c_void_p, C.c_void_p]),
    ("wl_display_roundtrip_queue", C.c_int, [C.c_void_p, C.c_void_p]),
    ("wl_display_dispatch_queue_pending", C.c_int, [C.c_void_p, C.c_void_p]),
    ("wl_display_flush", C.c_int, [C.c_void_p]),
):
    f = getattr(_wl, nome)
    f.restype, f.argtypes = res, args
_wl.wl_proxy_marshal_flags.restype = C.c_void_p     # variádica: tipos por chamada
for nome in ("gdk_wayland_display_get_wl_display", "gdk_wayland_surface_get_wl_surface"):
    f = getattr(_gtk, nome)
    f.restype, f.argtypes = C.c_void_p, [C.c_void_p]
C.pythonapi.PyCapsule_GetPointer.restype = C.c_void_p
C.pythonapi.PyCapsule_GetPointer.argtypes = [C.py_object, C.c_char_p]

_REGISTRO = _Iface.in_dll(_wl, "wl_registry_interface")
_COMPOSITOR = _Iface.in_dll(_wl, "wl_compositor_interface")
_SUPERFICIE = _Iface.in_dll(_wl, "wl_surface_interface")
_REGIAO = _Iface.in_dll(_wl, "wl_region_interface")
_DESTROI = 1    # WL_MARSHAL_FLAG_DESTROY


def _tipos(*ifaces):
    arr = (C.c_void_p * max(1, len(ifaces)))(*[C.addressof(i) if i is not None else None for i in ifaces])
    return C.cast(arr, C.POINTER(C.c_void_p)), arr


# Interfaces do protocolo, na ordem do XML (opcode = posição).
_EFEITO = _Iface()
_GERENTE = _Iface()
_t_vazio, _a0 = _tipos(None)
_t_regiao, _a1 = _tipos(_REGIAO)
_t_criar, _a2 = _tipos(_EFEITO, _SUPERFICIE)
_m_efeito = (_Msg * 2)(_Msg(b"destroy", b"", _t_vazio), _Msg(b"set_blur_region", b"?o", _t_regiao))
_m_gerente = (_Msg * 2)(_Msg(b"destroy", b"", _t_vazio), _Msg(b"get_background_effect", b"no", _t_criar))
_e_gerente = (_Msg * 1)(_Msg(b"capabilities", b"u", _t_vazio))
_EFEITO.name, _EFEITO.version = b"ext_background_effect_surface_v1", 1
_EFEITO.method_count, _EFEITO.methods = 2, _m_efeito
_EFEITO.event_count, _EFEITO.events = 0, None
_GERENTE.name, _GERENTE.version = b"ext_background_effect_manager_v1", 1
_GERENTE.method_count, _GERENTE.methods = 2, _m_gerente
_GERENTE.event_count, _GERENTE.events = 1, _e_gerente

_GLOBAL = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_uint32, C.c_char_p, C.c_uint32)
_REMOVE = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_uint32)
_CAPS = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_uint32)


def _ptr(obj) -> int:
    return C.pythonapi.PyCapsule_GetPointer(obj.__gpointer__, None)


def _marshal(proxy, opcode, iface, flags, *args, versao=None):
    if versao is None:
        versao = _wl.wl_proxy_get_version(proxy)
    return _wl.wl_proxy_marshal_flags(C.c_void_p(proxy), C.c_uint32(opcode),
                                      C.c_void_p(C.addressof(iface) if iface is not None else None),
                                      C.c_uint32(versao), C.c_uint32(flags), *args)


class Desfoque:
    def __init__(self, janela):
        self.janela = janela
        self.ok = False
        self.erro = ""
        self._efeito = None
        self._regiao = "nada"
        self._globais: dict[str, tuple[int, int]] = {}
        self._caps = 0
        try:
            self._iniciar()
        except Exception as e:  # sem Wayland, sem protocolo: fica só o vidro pintado
            self.erro = str(e)
        janela.connect("unrealize", lambda *_: self._soltar())

    def _iniciar(self):
        disp = Gdk.Display.get_default()
        self.display = _gtk.gdk_wayland_display_get_wl_display(_ptr(disp))
        if not self.display:
            raise RuntimeError("display não é Wayland")
        self.fila = _wl.wl_display_create_queue(self.display)
        emb = _wl.wl_proxy_create_wrapper(self.display)
        _wl.wl_proxy_set_queue(emb, self.fila)
        self.registro = _marshal(emb, 1, _REGISTRO, 0, None)
        _wl.wl_proxy_wrapper_destroy(emb)

        def ao_global(_d, _r, nome, iface, versao):
            self._globais[iface.decode()] = (nome, versao)

        self._cb = (_GLOBAL(ao_global), _REMOVE(lambda *_: None),
                    _CAPS(lambda _d, _g, f: setattr(self, "_caps", f)))
        self._ouvinte_reg = (C.c_void_p * 2)(C.cast(self._cb[0], C.c_void_p), C.cast(self._cb[1], C.c_void_p))
        _wl.wl_proxy_add_listener(self.registro, self._ouvinte_reg, None)
        _wl.wl_display_roundtrip_queue(self.display, self.fila)
        if "ext_background_effect_manager_v1" not in self._globais:
            raise RuntimeError("compositor sem ext-background-effect")

        def ligar(nome_iface, iface):
            nome, versao = self._globais[nome_iface]
            versao = min(versao, iface.version)
            return _marshal(self.registro, 0, iface, 0, C.c_uint32(nome), C.c_char_p(iface.name),
                            C.c_uint32(versao), None, versao=versao)

        self.compositor = ligar("wl_compositor", _COMPOSITOR)
        self.gerente = ligar("ext_background_effect_manager_v1", _GERENTE)
        self._ouvinte_ger = (C.c_void_p * 1)(C.cast(self._cb[2], C.c_void_p))
        _wl.wl_proxy_add_listener(self.gerente, self._ouvinte_ger, None)
        _wl.wl_display_roundtrip_queue(self.display, self.fila)
        self.ok = bool(self._caps & 1)
        if not self.ok:
            self.erro = "compositor não anuncia blur"

    def _soltar(self):
        """A wl_surface vai embora no unrealize; o efeito sai antes dela."""
        if self._efeito:
            _marshal(self._efeito, 0, None, _DESTROI)
            self._efeito = None
        self._regiao = "nada"

    def aplicar(self, retangulos):
        """Lista de (x, y, w, h) em coordenadas da superfície; None tira o efeito."""
        if not self.ok:
            return
        chave = None if retangulos is None else tuple(retangulos)
        if chave == self._regiao:
            return
        surf = self.janela.get_surface()
        if surf is None:
            return
        if self._efeito is None:
            wl_surf = _gtk.gdk_wayland_surface_get_wl_surface(_ptr(surf))
            if not wl_surf:
                return
            self._efeito = _marshal(self.gerente, 1, _EFEITO, 0, None, C.c_void_p(wl_surf))
        if chave is None:
            _marshal(self._efeito, 1, None, 0, C.c_void_p(None))
        else:
            reg = _marshal(self.compositor, 1, _REGIAO, 0, None)
            for x, y, w, h in chave:
                _marshal(reg, 1, None, 0, C.c_int32(int(x)), C.c_int32(int(y)),
                         C.c_int32(int(w)), C.c_int32(int(h)))
            _marshal(self._efeito, 1, None, 0, C.c_void_p(reg))
            _marshal(reg, 0, None, _DESTROI)
        _wl.wl_display_flush(self.display)
        self._regiao = chave


def disco(cx: float, cy: float, r: float) -> list[tuple[int, int, int, int]]:
    """Círculo como faixas horizontais (wl_region só tem retângulos)."""
    out = []
    r = max(0.0, r)
    ri = int(r)
    for dy in range(-ri, ri):
        meia = (r * r - (dy + 0.5) ** 2) ** 0.5
        x0 = int(round(cx - meia))
        out.append((x0, int(cy) + dy, int(round(cx + meia)) - x0, 1))
    return out
