-- Practice stats: how long each turn's audio was, in ms. User turns: the
-- utterance audio the VAD cut (speech + its padding, pauses inside a held
-- turn included). Assistant turns: the TTS audio sent to the phone.
-- NULL on turns recorded before this migration — stats estimate those
-- from the word count.

ALTER TABLE turns ADD COLUMN audio_ms INTEGER;
