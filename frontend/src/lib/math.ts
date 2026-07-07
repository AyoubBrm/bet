/**
 * Calculate the factorial of a number n!
 */
export function factorial(n: number): number {
  if (n === 0 || n === 1) return 1;
  let result = 1;
  for (let i = 2; i <= n; i++) {
    result *= i;
  }
  return result;
}

/**
 * Poisson Probability Mass Function (PMF)
 * Calculates the exact probability of exactly k events occurring given average lambda.
 * P(X = k) = (lambda^k * e^-lambda) / k!
 */
export function poissonPMF(k: number, lambda: number): number {
  return (Math.pow(lambda, k) * Math.exp(-lambda)) / factorial(k);
}

/**
 * Poisson Cumulative Distribution Function (CDF)
 * Calculates the probability of 0 to k events occurring.
 * P(X <= k) = sum from i=0 to k of poissonPMF(i, lambda)
 */
export function poissonCDF(k: number, lambda: number): number {
  let cdf = 0;
  for (let i = 0; i <= k; i++) {
    cdf += poissonPMF(i, lambda);
  }
  return cdf;
}

export interface EdgeResult {
  probability: number;
  expectedReturn: number;
  evAtBookOdds: number;
  edgeVsFairOdds: number;
  bookImpliedProbability: number;
  fairMarketProbability: number;
  fairMarketOdds: number;
  modelFairOdds: number;
}

/**
 * Master calculation function based on the user's Edge formula.
 *
 * @param lineStr - The exact string from Bet365 (e.g. "Shot 1+", "Shot 2+", "Tackle 3+")
 * @param odds - The numerical odds from Bet365 (e.g. 2.15)
 * @param lambda - The Expected Value (e.g. average shots per 90)
 */
export function calculateEdgeData(
  lineStr: string, 
  odds: number | undefined, 
  lambda: number | undefined,
  bookmakerMargin: number = 0.06
): EdgeResult | null {
  if (odds === undefined || lambda === undefined || isNaN(odds) || isNaN(lambda) || lambda === 0) {
    return null;
  }

  // 1. Extract the number from the line string (e.g., "Shot 2+" -> 2)
  const lineNum = parseInt(lineStr.replace(/\D/g, ""), 10);
  if (isNaN(lineNum)) return null;

  // 2. A "1+" bet means "Over 0.5". The formula dictates we use the integer part of the line.
  // So if Bet365 says "2+" (Over 1.5), the integer part of the line is 1.
  const lineInteger = lineNum - 1;

  // 3. Probability = 1 - Poisson CDF(line, lambda)
  const probability = 1 - poissonCDF(lineInteger, lambda);

  // 4. Expected Return = Probability * Odds
  const expectedReturn = probability * odds;

  // 5. Convert the bookmaker odds into fair odds
  const bookImpliedProbability = 1 / odds;
  const fairMarketProbability = bookImpliedProbability / (1 + bookmakerMargin);
  const fairMarketOdds = 1 / fairMarketProbability;

  // 6. Calculate model fair odds
  const modelFairOdds = probability > 0 ? 1 / probability : 0;

  // 7. Calculate edges
  const evAtBookOdds = expectedReturn - 1;
  const edgeVsFairOdds = modelFairOdds > 0 ? (fairMarketOdds / modelFairOdds) - 1 : 0;

  return {
    probability,
    expectedReturn,
    evAtBookOdds,
    edgeVsFairOdds,
    bookImpliedProbability,
    fairMarketProbability,
    fairMarketOdds,
    modelFairOdds
  };
}
