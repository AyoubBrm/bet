export interface PlayerOdds {
  [key: string]: number; // e.g., "shot 1+": 1.142
}

export interface Player {
  player: string;
  odds: PlayerOdds;
}

export interface MatchDetails {
  id: number;
  home: string;
  away: string;
  date: string;
}

export interface MatchEntry {
  match: MatchDetails;
  player_shots?: Player[];
  player_tackles?: Player[];
}

export interface ApiResponse {
  num_of_matches: number;
  matches: MatchEntry[];
}

export interface SofascorePlayerStat {
  totalTackle_in_number_of_match_s: number;
  totalShots_in_number_of_match_s: number;
  minutesPlayed_in_number_of_match_s: number;
  minutesPlayed_per_90_minutes: number;
  tackles_per_90_minutes: number;
  shots_per_90_minutes: number;
}

export interface SofascoreMatchHistory {
  statistics: SofascorePlayerStat;
}

export interface SofascorePlayer {
  player_id: number;
  name: string;
  number_of_match_s: number;
  matchs: SofascoreMatchHistory[];
}

export interface SofascoreMatch {
  match_id: number;
  teams: string;
  players: SofascorePlayer[];
  number_of_player_s: number;
}

export interface SofascoreResponse {
  match_count: number;
  total_number_of_player_s: number;
  matches: SofascoreMatch[];
}
