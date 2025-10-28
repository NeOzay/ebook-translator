# from ebooklib import epub
# from ebook_translator.segment import Segmentator
# from ebook_translator.translation.epub_handler import extract_html_items_in_spine_order
#
# epub_path = "./books/Chillin' in Another World With Level 2 Super Cheat Powers - Volume 01 [J-Novel Club][Premium].epub"
# source_book = epub.read_epub(epub_path)
# html_items, target_book = extract_html_items_in_spine_order(source_book)
# segmentator = Segmentator(html_items, 300, overlap_ratio=2)
#
# list_of_segments = list(segmentator.get_all_segments())
# print(f"Nombre total de segments extraits : {len(list_of_segments)}")
#

from tm2tb import BitermExtractor, TermExtractor

en_sentence = ()


fr_sentence = (
    "Chapitre 1 : La configuration du terrain\n"
    "◇Quelque part dans une forêt◇\n"
    "Sans aucun avertissement, un portail magique apparut au plus profond des bois. Alors qu'il se stabilisait, un homme et une femme prirent forme.\n"
    "Rys posa le pied sur le sol et regarda vers un village qu'elle pouvait voir de l'autre côté de la forêt. « Est-ce là, mon seigneur et mari ? »\n"
    "« Aucune erreur possible », dit Flio. « C'est bien l'endroit. » Il s'assura que le cercle se refermait correctement derrière lui et partit en courant vers le village.\n"
    "« Attends, mon amour ! » s'écria Rys. « Si nous y allons avec cette apparence, ils devineront qui nous sommes ! »\n"
    "« Oh ! C'est vrai ! » Flio s'arrêta net aux paroles de Rys et commença à lancer un sort sur lui-même, matérialisant un masque de loup à fourrure bleue sur sa tête. Il leva la main pour l'ajuster légèrement, s'assurant qu'il était bien en place, puis regarda à nouveau son épouse. « Cela te paraît bien, Rys ? » demanda-t-il.\n"
    "« Oui, parfait ! »\n"
    "« Bien, alors dépêchons-nous ! » Une fois de plus, Flio partit en courant.\n"
    "« Oui ! » lança Rys, courant à ses côtés. Sa robe blanche étincela avant de disparaître. Maintenant nue, sa forme humaine se transforma jusqu'à ce qu'elle devienne un démon lupin à fourrure argentée. Ensemble, ils quittèrent la forêt, courant à toute vitesse vers le village — Flio portant un masque de loup bleu, et Rys, un démon lupin argenté.\n"
    "◇Le Village◇\n"
    "« Qu— Qu'est-ce que c'est ?! »\n"
    "« L'Armée des Ténèbres ?! »\n"
    "Des cris retentirent dans tout le village tandis que les gens couraient en tous sens. Une troupe de gobelins fonçait sur eux — environ trente de ces petits monstres. Derrière eux se trouvaient deux ogres, brandissant d'énormes massues de métal tout en avançant. Ils semblaient être ceux qui commandaient.\n"
)


# extractor = BitermExtractor(
#    (en_sentence, fr_sentence), tgt_lang="", src_lang="en"
# )  # Instantiate extractor with sentences
# biterms = extractor.extract_terms()  # Extract biterms
# print(biterms[:7])

extractor = TermExtractor(fr_sentence, lang="fr")
out = extractor.extract_terms(incl_pos=["PROPN", "NOUN"])
print(out[:20])
