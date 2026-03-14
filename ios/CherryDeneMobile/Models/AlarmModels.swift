import Foundation

struct OverviewResponse: Decodable {
    let sheds: [OverviewShed]
    let borehole: OverviewBorehole
}

struct OverviewShed: Decodable, Identifiable {
    var id: Int { shed_no }
    let shed: String
    let shed_no: Int
    let alarm_active: Bool
    let alarm_key: String
    let alarm_msg: String
    let sync_pill_text: String
}

struct OverviewBorehole: Decodable {
    let alarm_active: Bool
    let alarm_key: String
    let alarm_msg: String
    let sync_pill_text: String
}

struct AlarmItem: Identifiable {
    let id: String
    let source: String
    let title: String
    let message: String
    let syncText: String
}
