package com.goalstick.android.data

data class ConfigurationData(
    val wifiSsid: String,
    val wifiPassword: String,
    val teamAbbr: String,
    val celebrationDelaySeconds: Int = 0
)

data class GoalStickConfig(
    val teamAbbr: String?,
    val celebrationDelaySeconds: Int,
    val ipAddress: String? = null
)

object TeamData {
    val teams = listOf(
        "ANA" to "Anaheim Ducks",
        "ARI" to "Arizona Coyotes",
        "BOS" to "Boston Bruins",
        "BUF" to "Buffalo Sabres",
        "CGY" to "Calgary Flames",
        "CAR" to "Carolina Hurricanes",
        "CHI" to "Chicago Blackhawks",
        "COL" to "Colorado Avalanche",
        "CBJ" to "Columbus Blue Jackets",
        "DAL" to "Dallas Stars",
        "DET" to "Detroit Red Wings",
        "EDM" to "Edmonton Oilers",
        "FLA" to "Florida Panthers",
        "LAK" to "Los Angeles Kings",
        "MIN" to "Minnesota Wild",
        "MTL" to "Montreal Canadiens",
        "NSH" to "Nashville Predators",
        "NJD" to "New Jersey Devils",
        "NYI" to "New York Islanders",
        "NYR" to "New York Rangers",
        "OTT" to "Ottawa Senators",
        "PHI" to "Philadelphia Flyers",
        "PIT" to "Pittsburgh Penguins",
        "SEA" to "Seattle Kraken",
        "SJS" to "San Jose Sharks",
        "STL" to "St. Louis Blues",
        "TBL" to "Tampa Bay Lightning",
        "TOR" to "Toronto Maple Leafs",
        "VAN" to "Vancouver Canucks",
        "VGK" to "Vegas Golden Knights",
        "WSH" to "Washington Capitals",
        "WPG" to "Winnipeg Jets"
    )
}
