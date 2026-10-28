"""Conversão DN -> reflectância de superfície.

Este é o ÚNICO ponto do sistema que aplica scale/offset. O rasterio não aplica
os metadados de scale/offset ao ler, então a leitura sempre devolve DN cru e a
conversão acontece aqui, uma vez. Arrays float nunca passam por aqui (o tipo é
checado), o que impede a dupla conversão.
"""

import numpy as np
import numpy.typing as npt


class RadiometryError(ValueError):
    pass


def dn_to_reflectance(
    dn: npt.NDArray[np.integer], scale: float, offset: float, nodata_dn: int
) -> npt.NDArray[np.float32]:
    """Converte DN inteiro em reflectância float32 (>= 0); NoData vira NaN."""
    if not np.issubdtype(dn.dtype, np.integer):
        raise RadiometryError(
            f"esperado DN inteiro, recebido {dn.dtype}: dado já convertido não pode ser reconvertido"
        )
    refl = dn.astype(np.float32) * np.float32(scale) + np.float32(offset)
    # Com offset -0.1, DN < 1000 vira reflectância negativa (ruído da correção
    # atmosférica em alvos escuros). Recortar em 0 mantém os índices em [-1, 1].
    np.maximum(refl, 0, out=refl)
    refl[dn == nodata_dn] = np.nan
    return refl


def resolve_scale_offset(
    file_scales: tuple[float, ...],
    file_offsets: tuple[float, ...],
    default_scale: float,
    default_offset: float,
) -> tuple[tuple[float, ...], tuple[float, ...], str]:
    """Escolhe scale/offset por banda: os do arquivo, se existirem, senão os da config.

    GDAL reporta scale=1 e offset=0 quando o arquivo não tem esses metadados;
    nesse caso usamos os valores padrão do Sentinel-2 L2A (baseline >= 04.00).
    """
    has_metadata = any(s != 1.0 for s in file_scales) or any(o != 0.0 for o in file_offsets)
    if has_metadata:
        return tuple(file_scales), tuple(file_offsets), "metadados do GeoTIFF"
    n = len(file_scales)
    return (default_scale,) * n, (default_offset,) * n, "padrão da configuração (S2 L2A)"
