import Foundation

struct OverviewResponse: Decodable {
    let sheds: [OverviewShed]
    let borehole: OverviewBorehole
    let overall: OverviewOverall
}

struct OverviewShed: Decodable, Identifiable {
    var id: Int { shed_no }
    let shed: String
    let shed_no: Int
    let has_data: Bool
    let has_active_entry: Bool
    let tile_state: String
    let temp_c: String
    let rh_pct: String
    let feed_kg: String
    let feed_glow: String
    let water_lpm: String
    let water_glow: String
    let crop_id: String
    let farm_crop_id: String
    let bird_count: String
    let birds_remaining: String
    let birds_placed: String
    let bird_age: String
    let water_7to7: String
    let feed_7to7: String
    let l_per_bird: String
    let kg_per_bird: String
    let avg_feed_per_bird: String
    let runout_est: String
    let updated: String
    let total_water_to_date: String
    let total_feed_to_date: String
    let allocation_text: String
    let mortality_total: String
    let mortality_pct: String
    let mortality_display: String
    let alarm_active: Bool
    let alarm_key: String
    let alarm_msg: String
    let sync_pill_class: String
    let sync_pill_text: String
}

struct OverviewBorehole: Decodable {
    let has_data: Bool
    let tile_state: String
    let water_lpm: String
    let water_glow: String
    let daily_water: String
    let weekly_water: String
    let last_7_days: [BoreholeDay]
    let updated: String
    let alarm_active: Bool
    let alarm_key: String
    let alarm_msg: String
    let sync_pill_class: String
    let sync_pill_text: String
}

struct BoreholeDay: Decodable, Identifiable {
    var id: String { label }
    let label: String
    let water: String
}

struct OverviewOverall: Decodable {
    let tile_state: String
    let birds_placed: String
    let birds_remaining: String
    let mortality_display: String
    let water: String
    let feed: String
    let farm_crop_id: String
}

struct AlarmItem: Identifiable {
    let id: String
    let source: String
    let title: String
    let message: String
    let syncText: String
}
