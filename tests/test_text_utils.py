import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup
from adapters import get_adapter
from adapters.arretsurimages import ArretSurImagesAdapter
from adapters.lemonde import LeMondeDiplomatiqueAdapter
from adapters.mediapart import MediapartAdapter
from adapters.reader_mode import reader_extract_content
from adapters.ucl import UCLAdapter
from text_utils import (
    apply_pronunciation_dict,
    build_article_intro,
    clean_text_for_tts,
    convertir_chiffres_romains,
    format_list_item_for_tts,
    normalize_all_caps,
    normalize_for_tts,
    prepare_text_for_tts,
    process_inclusive_writing,
    strip_leading_duplicate_title,
)


class TestInclusiveWriting(unittest.TestCase):
    def test_homophones_keep_masculine(self):
        self.assertEqual(process_inclusive_writing("les député·es"), "les députés")
        self.assertEqual(process_inclusive_writing("des salarié·es"), "des salariés")
        self.assertEqual(process_inclusive_writing("Fier.e.s"), "Fiers")
        self.assertEqual(process_inclusive_writing("professionnel·le"), "professionnel")
        self.assertEqual(process_inclusive_writing("professionnel·les"), "professionnels")
        self.assertEqual(process_inclusive_writing("inverti.e.s"), "invertis")
        self.assertEqual(process_inclusive_writing("d’élu·es"), "d’élus")

    def test_eur_trice_euse_are_not_homophones(self):
        self.assertEqual(
            process_inclusive_writing("les spectateur·ices"),
            "les spectatrices et spectateurs",
        )
        self.assertEqual(
            process_inclusive_writing("un·e lecteur·rice"),
            "une ou un lectrice et lecteur",
        )
        self.assertEqual(
            process_inclusive_writing("les auteur·ices"),
            "les autrices et auteurs",
        )
        self.assertEqual(
            process_inclusive_writing("les chercheur·euses"),
            "les chercheuses et chercheurs",
        )
        self.assertEqual(
            process_inclusive_writing("des chercheur·ses"),
            "des chercheuses et chercheurs",
        )

    def test_morphological_variants_and_plurals(self):
        self.assertEqual(
            process_inclusive_writing("divers·es"),
            "diverses et divers",
        )
        self.assertEqual(
            process_inclusive_writing("Taïwanais·es"),
            "Taïwanaises et taïwanais",
        )
        self.assertEqual(
            process_inclusive_writing("Afro-Américain·es"),
            "Afro-Américaines et Afro-Américains",
        )
        self.assertEqual(process_inclusive_writing("juif.ves"), "juives et juifs")
        self.assertEqual(process_inclusive_writing("bon.nes"), "bonnes et bons")
        self.assertEqual(process_inclusive_writing("premier·ère·s"), "premières et premiers")
        self.assertEqual(process_inclusive_writing("tou·te·s"), "toutes et tous")
        self.assertEqual(process_inclusive_writing("tous·tes"), "toutes et tous")
        self.assertEqual(process_inclusive_writing("tou-te-s"), "toutes et tous")

    def test_elisions_and_parentheses(self):
        self.assertEqual(
            process_inclusive_writing("quelqu’un.e"),
            "quelqu’une ou quelqu’un",
        )
        self.assertEqual(
            process_inclusive_writing("d’avocat·es"),
            "d’avocates et d’avocats",
        )
        self.assertEqual(process_inclusive_writing("d’un.e"), "d’une ou d’un")
        self.assertEqual(
            process_inclusive_writing("étudiant(e)"),
            "étudiante et étudiant",
        )
        self.assertEqual(
            process_inclusive_writing("étudiant(e)s"),
            "étudiantes et étudiants",
        )
        self.assertEqual(
            process_inclusive_writing("étudiant(e)(s)"),
            "étudiantes et étudiants",
        )

    def test_neologisms_and_slashes(self):
        self.assertEqual(process_inclusive_writing("il/elle/iel"), "elle ou il")
        self.assertEqual(process_inclusive_writing("Il/elle"), "Elle ou il")
        self.assertEqual(process_inclusive_writing("celleux"), "celles et ceux")
        self.assertEqual(process_inclusive_writing("toustes"), "toutes et tous")
        self.assertEqual(process_inclusive_writing("iels"), "elles et ils")

    def test_non_regression_hyphens_and_domains(self):
        self.assertEqual(
            process_inclusive_writing("un porte-parole à Saint-Étienne"),
            "un porte-parole à Saint-Étienne",
        )
        self.assertEqual(
            process_inclusive_writing("visitez https://elpais.es/mundo"),
            "visitez https://elpais.es/mundo",
        )


class TestRomanNumeralsAndOrdinals(unittest.TestCase):
    def test_centuries_and_detached_sup(self):
        self.assertEqual(convertir_chiffres_romains("au XIXe siècle"), "au 19e siècle")
        self.assertEqual(convertir_chiffres_romains("au XIX e siècle"), "au 19e siècle")
        self.assertEqual(convertir_chiffres_romains("du XVIIIe au XXe siècles"), "du 18e au 20e siècles")
        self.assertEqual(convertir_chiffres_romains("au Ve siècle"), "au 5e siècle")
        self.assertEqual(convertir_chiffres_romains("le 1 er mai"), "le 1er mai")

    def test_republics_reich_arrondissements(self):
        self.assertEqual(convertir_chiffres_romains("la Vème République"), "la 5e République")
        self.assertEqual(convertir_chiffres_romains("la VI e République"), "la 6e République")
        self.assertEqual(convertir_chiffres_romains("la IIIe République"), "la 3e République")
        self.assertEqual(convertir_chiffres_romains("la Ie République"), "la 1re République")
        self.assertEqual(convertir_chiffres_romains("le III e Reich"), "le 3e Reich")
        self.assertEqual(convertir_chiffres_romains("Paris IV"), "Paris 4e")
        self.assertEqual(convertir_chiffres_romains("Xe arrondissement"), "10e arrondissement")

    def test_sovereigns_popes_and_structures(self):
        self.assertEqual(convertir_chiffres_romains("lycée Henri-IV"), "lycée Henri 4")
        self.assertEqual(convertir_chiffres_romains("pape Léon XIV"), "pape Léon 14")
        self.assertEqual(convertir_chiffres_romains("Benoît XVI"), "Benoît 16")
        self.assertEqual(convertir_chiffres_romains("François Ier"), "François 1er")
        self.assertEqual(convertir_chiffres_romains("Charles III"), "Charles 3")
        self.assertEqual(convertir_chiffres_romains("chapitre IV, tome II"), "chapitre 4, tome 2")
        self.assertEqual(convertir_chiffres_romains("Vatican II"), "Vatican 2")

    def test_non_regression_proper_nouns_and_e_commerce(self):
        self.assertEqual(convertir_chiffres_romains("Xi Jinping"), "Xi Jinping")
        self.assertEqual(convertir_chiffres_romains("Le 5 octobre"), "Le 5 octobre")
        self.assertEqual(convertir_chiffres_romains("De Gaulle"), "De Gaulle")
        self.assertEqual(convertir_chiffres_romains("Plan X e-commerce"), "Plan X e-commerce")


class TestCleanAndNormalizeTTS(unittest.TestCase):
    def test_preserves_names_with_numbers(self):
        sample = (
            "Sur TF1, France 5, M6, C8, CCTV13, et L214. "
            "Gemini 4, GPT-4, Claude 3, DeepSeek R1, MD5, CO2, G20, phase N3. "
            "Une surface de 12 m² et 3 km²."
        )
        cleaned = clean_text_for_tts(sample)
        for token in ("TF1,", "France 5,", "M6,", "C8,", "CCTV13,", "L214.", "Gemini 4,", "R1,", "MD5,", "CO2,", "G20,", "N3.", "m²", "km²"):
            self.assertIn(token, cleaned)

    def test_strips_real_footnotes_and_preserves_sentence_starting_with_number(self):
        sample = (
            "Selon cette étude[1], le phénomène augmente12. "
            "La réforme¹² est votée. 14 Juillet est férié. "
            "Voir [le ministre – ndlr] et […] ainsi que [son] discours."
        )
        cleaned = clean_text_for_tts(sample)
        self.assertIn("cette étude, le phénomène augmente.", cleaned)
        self.assertIn("La réforme est votée.", cleaned)
        self.assertIn("14 Juillet est férié.", cleaned)
        self.assertIn("le ministre – note de la rédaction", cleaned)
        self.assertIn("et... ainsi que son discours.", cleaned)

    def test_normalize_and_prepare_pipeline(self):
        raw = (
            'L’article 49.3 au XIX e siècle sur TF1, avec ""des"" spectateur·ices, '
            "n° 12, CO 2, et/ou Gemini 4."
        )
        prepared = prepare_text_for_tts(raw)
        self.assertIn("49 3", prepared)
        self.assertIn("19e siècle", prepared)
        self.assertIn("TF1,", prepared)
        self.assertIn("spectatrices et spectateurs", prepared)
        self.assertIn("numéro 12", prepared)
        self.assertIn("CO2", prepared)
        self.assertIn("et ou", prepared)
        self.assertIn("Gemini 4.", prepared)
        self.assertNotIn('""', prepared)

    def test_reader_mode_no_synthetic_double_quotes(self):
        html = "<html><body><article><p>Un texte avec <strong>un mot en gras</strong> et <em>un autre</em>.</p></article></body></html>"
        extracted = reader_extract_content(html)
        self.assertNotIn('""', extracted)
        self.assertNotIn('"', extracted)
        self.assertIn("un mot en gras", extracted)

    def test_unicode_artifacts_and_html_spacing(self):
        raw = (
            "Politiser la ques\xadtion du han\xaddi\xadcap\u200b dans l’ asso "
            "et d’ Écotransféminismes ( ableism ) avec note↩︎."
        )
        cleaned = clean_text_for_tts(raw)
        self.assertNotIn('\xad', cleaned)
        self.assertNotIn('\u200b', cleaned)
        self.assertNotIn('↩', cleaned)
        self.assertIn("question du handicap", cleaned)
        self.assertIn("dans l’asso", cleaned)
        self.assertIn("d’Écotransféminismes", cleaned)
        self.assertIn("(ableism)", cleaned)

    def test_punctuation_collisions_and_boilerplate(self):
        raw = (
            "Pourquoi?. Pour ça!.. Voici:. Et aussi., puis,. encore?... "
            "557vues. à l’échelle du monde ( 9 ). "
            "Inscrivez-vous à notre newsletter chaque semaine. "
            "Rendez-vous sur Cooperationjackson.org/. "
            "Cette phrase suffisamment longue décrit un fait important dans l'article. "
            "Cette phrase suffisamment longue décrit un fait important dans l'article. "
            "Suite du texte."
        )
        cleaned = clean_text_for_tts(raw)
        for bad in ("?.", "!.", ":.", ".,", ",.", "?...", "557vues", "(9)", "Inscrivez-vous", "Cooperationjackson.org/"):
            self.assertNotIn(bad, cleaned)
        self.assertEqual(cleaned.count("Cette phrase suffisamment longue décrit un fait important dans l'article."), 1)
        self.assertIn("Suite du texte.", cleaned)

    def test_vocal_abbreviations_and_currency_units(self):
        sample = "En 50 av. J.-C. et 100 ap. J.-C., cf. p. 42 et pp. 12-15, c.-à-d. vol. 3 : 2,5 Md€, 1 Md€ et 50 k€."
        norm = normalize_for_tts(sample)
        self.assertIn("50 avant Jésus-Christ", norm)
        self.assertIn("100 après Jésus-Christ", norm)
        self.assertIn("voir page 42", norm)
        self.assertIn("pages 12-15", norm)
        self.assertIn("c'est-à-dire", norm)
        self.assertIn("volume 3", norm)
        self.assertIn("2,5 milliards d'euros", norm)
        self.assertIn("1 milliard d'euros", norm)
        self.assertIn("50 mille euros", norm)

    def test_intro_and_duplicate_title_stripping(self):
        self.assertEqual(
            build_article_intro("Mon titre", "Unknown Author", "Unknown Media"),
            "Mon titre... ",
        )
        self.assertEqual(
            build_article_intro("Mon titre", "Union communiste libertaire", "Union Communiste Libertaire"),
            "Article de Union Communiste Libertaire... Mon titre... ",
        )
        self.assertEqual(
            build_article_intro("Mon titre", "Jean Dupont", "Acrimed | Action Critique Médias"),
            "Article de Acrimed... Mon titre... Par Jean Dupont... ",
        )
        body = "« Parlons de santé mentale » : folie douce. Les productions médiatiques sur la santé mentale se multiplient."
        stripped = strip_leading_duplicate_title('"Parlons de santé mentale" : folie douce', body)
        self.assertTrue(stripped.startswith("Les productions médiatiques"))
        # Ne doit pas couper si le titre n'est que le début d'une phrase différente
        non_dup = "La crise sociale s'aggrave dans le pays depuis plusieurs mois déjà."
        self.assertEqual(strip_leading_duplicate_title("La crise sociale", non_dup), non_dup)

    def test_normalize_all_caps_preserves_acronyms(self):
        raw = "[ALLIER] CONTRE LA GUEULETONNADE DES CHEMISES BRUNES : PAS DE FASCISTES DANS NOS CAMPAGNES !"
        norm = normalize_all_caps(raw)
        self.assertIn("Contre la gueuletonnade des chemises brunes : Pas de fascistes dans nos campagnes !", norm)
        # Les sigles isolés et listes de sigles restent intacts
        sigles = "Selon LFI, RN, PS et UE sur TF1 avec CO2 et PFAS."
        self.assertEqual(normalize_all_caps(sigles), sigles)
        # Même à l'intérieur d'un titre en majuscules, les sigles connus restent en majuscules
        mixed = "CONTRE LA POLITIQUE DE LFI ET DU RN EN FRANCE"
        self.assertIn("LFI", normalize_all_caps(mixed))
        self.assertIn("RN", normalize_all_caps(mixed))

    def test_visual_cross_refs_mediapart_newsletter_and_pronunciation_dict(self):
        raw = (
            "Voulez-vous plonger dans les secrets de fabrication de nos révélations ? "
            "Rejoignez la « lettre enquête » pour découvrir nos coulisses. "
            "Un fait central (lire l’intégralité de la réponse en annexes) et un autre (voir ci-dessous). "
            "Le graphique (ci-contre) montre l'évolution."
        )
        cleaned = clean_text_for_tts(raw)
        self.assertNotIn("secrets de fabrication", cleaned)
        self.assertNotIn("lettre enquête", cleaned)
        self.assertNotIn("en annexes", cleaned)
        self.assertNotIn("ci-dessous", cleaned)
        self.assertNotIn("ci-contre", cleaned)
        self.assertIn("Un fait central et un autre.", cleaned)

        spoken = apply_pronunciation_dict("Les PFAS sur BFMTV.", {"PFAS": "péfasse", "BFMTV": "B F M T V"})
        self.assertEqual(spoken, "Les péfasse sur B F M T V.")

    def test_format_list_item_punctuation(self):
        self.assertEqual(format_list_item_for_tts("Un point court"), "Un point court,")
        long_item = "Un élément de liste très développé qui contient beaucoup plus de quatre-vingts caractères pour tester le point final"
        self.assertTrue(format_list_item_for_tts(long_item).endswith("."))
        multi_sentence = "Première phrase. Deuxième phrase"
        self.assertTrue(format_list_item_for_tts(multi_sentence).endswith("."))


class TestAdaptersCleanup(unittest.TestCase):
    def test_mediapart_removes_aside_newsletter_and_highlight(self):
        html = """
        <html><body>
        <div class="news__rich-text-content">
            <p>Premier paragraphe complet de l'article Mediapart.</p>
            <aside class="highlight"><p>Premier paragraphe complet de l'article Mediapart.</p></aside>
            <aside><p>Inscrivez-vous à « L’éco à part » et recevez notre analyse.</p></aside>
            <p>Deuxième paragraphe de l'article Mediapart.</p>
        </div>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        adapter = MediapartAdapter(soup, "mediapart.html")
        content = adapter.get_content()
        self.assertEqual(content.count("Premier paragraphe"), 1)
        self.assertNotIn("Inscrivez-vous", content)
        self.assertIn("Deuxième paragraphe", content)

    def test_mediapart_extracts_chapo_and_box_segments(self):
        html = """
        <html><body>
        <div class="news__heading__top__intro">Voici le chapô exclusif de l'article Mediapart.</div>
        <div class="news__rich-text-content">
            <p>Voulez-vous plonger dans les secrets de fabrication de nos révélations ?</p>
            <p>Premier paragraphe du corps principal.</p>
            <h2 class="subheading">Première partie</h2>
            <div class="box">
                <div class="box__header">Le pouvoir d’achat</div>
                <div class="box__content"><p>Contenu de l'encadré explicatif.</p></div>
            </div>
            <p>Deuxième paragraphe après l'encadré.</p>
        </div>
        </body></html>
        """
        adapter = MediapartAdapter(BeautifulSoup(html, "html.parser"), "mediapart.html")
        segs = adapter.get_segments()
        kinds = [s.kind for s in segs]
        self.assertEqual(kinds, ["chapo", "paragraph", "heading", "box_title", "box_body", "paragraph"])
        self.assertIn("chapô exclusif", segs[0].text)
        self.assertFalse(any("secrets de fabrication" in s.text for s in segs))

    def test_arretsurimages_extracts_author_from_equipe_or_title(self):
        html_equipe = """
        <html><head>
            <meta property="og:site_name" content="Arrêt sur images" />
            <meta property="og:title" content="Titre test | Arrêt sur images" />
        </head><body>
            <a href="/equipe/loris-guemart">Loris Guémart</a>
        </body></html>
        """
        meta1 = ArretSurImagesAdapter(BeautifulSoup(html_equipe, "html.parser"), "asi.html").extract_metadata()
        self.assertEqual(meta1["author"], "Loris Guémart")

        html_title = """
        <html><head>
            <meta property="og:site_name" content="Arrêt sur images" />
            <meta property="og:title" content="Sujet important - Par Pauline Bock | Arrêt sur images" />
        </head><body></body></html>
        """
        meta2 = ArretSurImagesAdapter(BeautifulSoup(html_title, "html.parser"), "asi.html").extract_metadata()
        self.assertEqual(meta2["title"], "Sujet important")
        self.assertEqual(meta2["author"], "Pauline Bock")

    def test_lemonde_removes_spip_note_ref(self):
        html = """
        <html><body>
        <div class="article-texte">
            <p>À l'échelle du monde<span class="spip_note_ref"> (<a class="spip_note" href="#nb1">9</a>)</span>.</p>
        </div>
        </body></html>
        """
        adapter = LeMondeDiplomatiqueAdapter(BeautifulSoup(html, "html.parser"), "lmd.html")
        content = adapter.get_content()
        self.assertNotIn("9", content)
        self.assertIn("À l'échelle du monde.", content)

    def test_ucl_does_not_hijack_basta_and_strips_views(self):
        basta_html = """
        <html><head><meta property="og:site_name" content="Basta!" /></head>
        <body><h1 class="entry-title">Titre Basta</h1><span class="vcard author">Auteur</span></body></html>
        """
        adapter = get_adapter(BeautifulSoup(basta_html, "html.parser"), "basta.html")
        self.assertNotIsInstance(adapter, UCLAdapter)

        ucl_html = """
        <html><head><meta property="og:url" content="https://www.unioncommunistelibertaire.org/?test" /></head>
        <body><div class="entry-content">
            <div class="post-date">11 octobre 2026 par AL / 557 vues</div>
            <p>Premier vrai paragraphe de l'article UCL suffisamment long pour passer le seuil d'extraction du reader mode.</p>
            <p>Deuxième vrai paragraphe de l'article UCL avec du contenu substantiel pour valider l'extraction.</p>
        </div></body></html>
        """
        ucl_adapter = UCLAdapter(BeautifulSoup(ucl_html, "html.parser"), "ucl.html")
        content = ucl_adapter.get_content()
        self.assertNotIn("557", content)
        self.assertNotIn("vues", content)
        self.assertIn("Premier vrai paragraphe", content)

    def test_mediapart_nested_p_aside_box_and_newsletter_insert(self):
        html = """
        <html><body>
        <div class="news__rich-text-content">
            <div class="newsletter-insert _compact"><p>Rejoignez la « lettre enquête » chaque samedi.</p></div>
            <p class="dropcap-wrapper">Texte un complet.<p>Texte deux complet.<aside class="box _set"><div class="box__header">Encadré titre</div><div class="box__content"><p>Contenu encadré.</p></div></aside><p>Texte trois complet.</p></p></p>
        </div>
        </body></html>
        """
        adapter = MediapartAdapter(BeautifulSoup(html, "html.parser"), "mediapart.html")
        segs = adapter.get_segments()
        kinds_texts = [(s.kind, s.text) for s in segs]
        self.assertNotIn("lettre enquête", " ".join(s.text for s in segs))
        self.assertEqual(kinds_texts, [
            ("paragraph", "Texte un complet."),
            ("paragraph", "Texte deux complet."),
            ("box_title", "Encadré titre"),
            ("box_body", "Contenu encadré."),
            ("paragraph", "Texte trois complet."),
        ])


if __name__ == "__main__":
    unittest.main()
