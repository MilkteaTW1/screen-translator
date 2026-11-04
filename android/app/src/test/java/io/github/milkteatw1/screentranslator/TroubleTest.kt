package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Test

class TroubleTest {
    @Test fun googleSayingNoIsToldAsRefusedAndAnUnreachableOneAsNetwork() {
        assertEquals("refused", Trouble.kind(true, "refused"))
        assertEquals("network", Trouble.kind(true, "unreachable"))
    }

    @Test fun whenGoogleIsOffOrFineTheOfflineModelIsTheLikelyCause() {
        assertEquals("offline", Trouble.kind(false, "refused"))
        assertEquals("offline", Trouble.kind(true, "ok"))
    }
}
