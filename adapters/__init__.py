

from .gemini import GeminiAdapter
from .europresse import EuropresseAdapter

from .lemonde import LeMondeDiplomatiqueAdapter
from .mediapart import MediapartAdapter
from .ucl import UCLAdapter
from .ballast import BallastAdapter
from .multitudes import MultitudesAdapter
from .manifesto import ManifestoAdapter
from .cairn import CairnAdapter
from .lmsi import LMSIAdapter
from .generic import GenericAdapter
import logging

logger = logging.getLogger(__name__)

def get_adapter(soup, filename):
    """
    Factory function to get the appropriate adapter for the given HTML soup.
    """
    adapters = [
        GeminiAdapter,
        EuropresseAdapter,
        LeMondeDiplomatiqueAdapter,
        MediapartAdapter,
        BallastAdapter,
        MultitudesAdapter,
        ManifestoAdapter,
        CairnAdapter,
        LMSIAdapter,
        UCLAdapter,  # UCL uses generic selectors, should be checked last
        # Add other adapters here
    ]



    for adapter_cls in adapters:
        adapter = adapter_cls(soup, filename)
        if adapter.can_handle():
            logger.info(f"Using adapter: {adapter_cls.__name__}")
            return adapter

    logger.info("Using adapter: GenericAdapter")
    return GenericAdapter(soup, filename)
