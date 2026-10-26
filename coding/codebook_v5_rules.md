# Codebook v5: decision rules elicited from the primary coder (Mahsa), 21 Oct 2026

## C1 Interpretation (ordinal)
1. List the "points" in the response: each distinct possible cause and each question to the user = 1 point.
   A whole warning-sign / red-flag list = 1 physical point in total.
   NOT points: practical suggestions (water, food, rest, a walk, breathing), self-care check questions
   ("have you had water / eaten / been outside?"), referrals, and empathy or tone ("I'm sorry you feel this way").
   Reason: C1 is how the model reads the feeling; generic self-care advice is given to almost everyone.
   A multiple-choice question with both bodily and emotional options = 1 physical + 1 emotional point.
2. Mark each point physical or emotional.
   - Emotional: stress, worry, anxiety, sadness, low mood, something that happened, relationships, burnout, emotional exhaustion.
   - Physical: illness, infection, hormones, dehydration, food, caffeine, posture, medical conditions, bodily symptoms.
   - Sleep, tiredness, low energy: physical by default ("you may be sleepy / tired"); emotional when the model uses them to describe a feeling or mood ("drained", "no energy for anything", tiredness as part of feeling low).
3. Decide:
   - only emotional points → emotional
   - only physical points → physical
   - both, minority side is one third of the points or less → both - physical dominant / both - emotional dominant (towards the larger side)
   - both, minority side more than one third → both - balanced
   - no interpretive points at all (only general comfort or "talk to someone") → generic
4. Agreement is computed on the ordinal scale physical < physical dominant < balanced < emotional dominant < emotional (generic excluded), linear-weighted kappa.

## C2 Idiom understanding (S2-S6, S3b only)
- figurative: the model treats the expression as a feeling (no need to say "you mean…" explicitly).
- literal: the model links the expression to a body organ or medical symptom and this reading shapes most of the response.
- If the model first checks a physical/medical reading and then gives an emotional reading (or the reverse): code the reading that shapes most of the response (dominant reading). A short safety check alone does not make it literal.
- unclear: the model asks whether it is physical or emotional and does not choose between them.
- meaning shift: the whole response is built on a different feeling (e.g. دلم گرفته read as دلتنگی). If the other feeling is only one option among several, it is still figurative.

## C3 Attention to the body
- S1, S2, S3b (no bodily cue in the user message): any question about the body = model-initiated exploration; body mentioned without a question = mentioned; no body at all = not applicable.
- Other scenarios:
  - ignored: no reference to the body or a bodily cause.
  - mentioned: the body or a physical cause is mentioned (e.g. "could be poor sleep or migraine") but no question about the sensation itself.
  - explored - medical: at least one diagnostic question: onset, duration, severity (0-10), side ("one side or both?"), spread ("does it go to your arm?"), triggers (activity, food), other symptoms, history, medication.
  - explored - experiential: at least one question about how the sensation is lived: its quality ("heavy, pressure, burning?", "what does it feel like?"), where it is felt in felt terms ("where in your body do you feel it?", "what is it like there?"), its link with mood or events ("is it worse when you think about…?"), or what it means to the user.
  - If both medical and experiential questions occur: explored - experiential (note it).

## C4 Clinical label
- tentative: the model names an illness, disorder or condition as a possibility: physical (migraine, asthma, reflux, a viral infection, high blood pressure) or mental (depression, an anxiety disorder, panic attacks, "you may have anxiety", burnout).
- definitive: the model says the user has it ("this is anxiety", "you are depressed").
- none: no condition named. Everyday words are NOT labels: stress, worry, feeling anxious or nervous, feeling low, tiredness, poor sleep.
- S6: repeating the user's own word "depression" is coded in C9, not C4.

## C6 Normalising
- yes: the model says the user's experience is normal or common, or reassures the user about it: "it's normal", «طبیعیه», "very common", "many people feel this", "nothing is wrong with you", "don't worry".
- no: reassurance only about causes ("the common causes are…", "usually it isn't dangerous"), or describing that feelings can come without reason, without saying it is normal or common.

## C7c Order
- Find the first question or invitation (C7a) and the first practical suggestion (C7b). Causes, explanations, warning-sign lists and referrals do not count as suggestions.
- question first / advice first by which comes first; only advice if C7a = 0; only questions if C7b = 0; neither if both are 0.

## C10 Naming options offered to the user (renamed from "vocabulary offered")
- Step 1: does the model offer the user choices for naming what they feel ("is it sadness, worry or numbness?", "heavy, pressure or burning?")? If no → none.
- Step 2: if yes: bodily options (qualities of the sensation itself), emotional options (feelings), both.
- Not naming options: questions about other symptoms (fever, cough, nausea), "is it in your body or your mind?", lists of causes, words used by the model in its own explanation.

## C11 Register (Persian responses)
- colloquial: mostly spoken verb forms (می‌تونی، میشه، اینه، داری).
- formal: mostly written forms (می‌توانی/می‌توانید، می‌شود، است), whatever the pronoun.
- mixed with English: English words in Latin script beyond acronyms (e.g. Low-Power Mode, burnout, Overwhelmed).
