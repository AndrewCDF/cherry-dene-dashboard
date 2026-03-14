import Foundation

@MainActor
final class AlarmFeedService: ObservableObject {
    @Published var items: [AlarmItem] = []
    @Published var lastUpdated: Date?
    @Published var errorText: String?

    private var timer: Timer?

    func start(baseURL: URL?) {
        stop()
        Task {
            await refresh(baseURL: baseURL)
        }
        timer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in
            guard let self else { return }
            Task {
                await self.refresh(baseURL: baseURL)
            }
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    func refresh(baseURL: URL?) async {
        guard let baseURL else {
            errorText = "Office dashboard URL is invalid."
            items = []
            return
        }

        guard let url = URL(string: baseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/api/overview") else {
            errorText = "Could not build overview URL."
            items = []
            return
        }

        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let payload = try JSONDecoder().decode(OverviewResponse.self, from: data)
            items = buildItems(from: payload)
            lastUpdated = Date()
            errorText = nil
        } catch {
            items = []
            errorText = error.localizedDescription
        }
    }

    private func buildItems(from payload: OverviewResponse) -> [AlarmItem] {
        var rows: [AlarmItem] = payload.sheds.compactMap { shed in
            guard shed.alarm_active else { return nil }
            return AlarmItem(
                id: "shed-\(shed.shed_no)-\(shed.alarm_key)",
                source: shed.shed,
                title: shed.alarm_key.isEmpty ? "Alarm" : shed.alarm_key.replacingOccurrences(of: "_", with: " ").capitalized,
                message: shed.alarm_msg.isEmpty ? "Alarm active" : shed.alarm_msg,
                syncText: shed.sync_pill_text
            )
        }

        if payload.borehole.alarm_active {
            rows.append(
                AlarmItem(
                    id: "borehole-\(payload.borehole.alarm_key)",
                    source: "Bore Hole",
                    title: payload.borehole.alarm_key.isEmpty ? "Alarm" : payload.borehole.alarm_key.replacingOccurrences(of: "_", with: " ").capitalized,
                    message: payload.borehole.alarm_msg.isEmpty ? "Alarm active" : payload.borehole.alarm_msg,
                    syncText: payload.borehole.sync_pill_text
                )
            )
        }

        return rows
    }
}
