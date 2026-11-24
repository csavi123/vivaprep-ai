# Judge rubric: when is a key concept "covered"?

**Tie-break test (use when unsure):** Could a student who read ONLY this answer state the
concept in their own words? Yes → covered. No, they'd have to guess or know it already → not covered.

1. **Same meaning, different words → covered.**
   Example (s1-02): concept "a score for every token"; answer says "one logit per vocabulary entry".
   A logit IS a score, so covered.

2. **Clearly implied but not said directly → covered, but only if it passes the tie-break test.**
   Example (s3-05): concept "nothing in the loop checks truth"; answer says the forward pass
   "does not compute truth… a statistical correlation rather than a guarantee". A reader clearly
   gets "nothing checks truth", so covered.

3. **Mentions the topic but not the actual point → not covered.**
   Example (s1-01): concept "sequence of tokens as input"; answer says "a batch of data or tokens".
   It names tokens, but not that the input IS a sequence of tokens, so not covered.

4. **Says something that contradicts the concept → not covered**, even if other parts sound right.
   Example (s2-05): concept "can't inspect the interior"; answer says interpretability tools
   "can trace internal components". That's the opposite, so not covered.

5. **Answer says "not in the course" → not covered** for every concept.
   (Reported separately as "abstained", so a safe refusal isn't confused with a wrong answer.)

6. **A concept with "or" / several examples → covered if the core idea is there.**
   Example (s3-06): concept "rare, recent, or company-specific information"; answer mentions
   obscure / long-tail facts. One of the listed kinds is enough, so covered.