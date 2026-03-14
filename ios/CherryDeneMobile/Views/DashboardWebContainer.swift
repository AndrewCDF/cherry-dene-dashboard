import SwiftUI
import Foundation
import WebKit

struct DashboardWebContainer: View {
    let title: String
    let subtitle: String
    let url: URL?

    @State private var reloadToken = UUID()

    var body: some View {
        NavigationStack {
            Group {
                if let url {
                    EmbeddedWebView(url: url, reloadToken: reloadToken)
                        .ignoresSafeArea(edges: .bottom)
                } else {
                    ContentUnavailableView(
                        "Invalid URL",
                        systemImage: "exclamationmark.triangle",
                        description: Text("Check the address in Settings.")
                    )
                }
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        reloadToken = UUID()
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .safeAreaInset(edge: .top) {
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal)
                    .padding(.top, 4)
            }
        }
    }
}

struct EmbeddedWebView: UIViewRepresentable {
    let url: URL
    let reloadToken: UUID

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.allowsBackForwardNavigationGestures = true
        webView.scrollView.keyboardDismissMode = .interactive
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        if webView.url != url {
            webView.load(URLRequest(url: url))
            return
        }
        if context.coordinator.lastReloadToken != reloadToken {
            context.coordinator.lastReloadToken = reloadToken
            webView.reload()
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    final class Coordinator {
        var lastReloadToken = UUID()
    }
}

@MainActor
final class OverviewService: ObservableObject {
    @Published var payload: OverviewResponse?
    @Published var lastUpdated: Date?
    @Published var errorText: String?

    private var timer: Timer?

    func start(baseURL: URL?) {
        stop()
        Task { await refresh(baseURL: baseURL) }
        timer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in
            guard let self else { return }
            Task { await self.refresh(baseURL: baseURL) }
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    func refresh(baseURL: URL?) async {
        guard let baseURL else {
            payload = nil
            errorText = "Office dashboard URL is invalid."
            return
        }

        guard let url = URL(string: baseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/api/overview") else {
            payload = nil
            errorText = "Could not build overview URL."
            return
        }

        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            payload = try JSONDecoder().decode(OverviewResponse.self, from: data)
            lastUpdated = Date()
            errorText = nil
        } catch {
            payload = nil
            errorText = error.localizedDescription
        }
    }
}

struct OfficeOverviewView: View {
    @EnvironmentObject private var settings: AppSettingsStore

    var body: some View {
        DashboardWebContainer(
            title: "Office",
            subtitle: settings.normalizedURL(settings.officeBaseURL),
            url: settings.officeDashboardURL
        )
    }
}

struct BoreholeOverviewView: View {
    @EnvironmentObject private var settings: AppSettingsStore

    var body: some View {
        DashboardWebContainer(
            title: "Bore Hole",
            subtitle: settings.normalizedURL(settings.officeBaseURL),
            url: settings.officeBoreholeURL
        )
    }
}

private struct OverallSummaryCard: View {
    let overall: OverviewOverall

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Current Crop Overall")
                    .font(.title3.weight(.bold))
                    .foregroundStyle(AppTheme.primaryText)
                Spacer()
                StatusChip(text: overall.tile_state == "online" ? "Online" : "Offline", tint: overall.tile_state == "online" ? AppTheme.goodGlow : AppTheme.badGlow)
            }
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                SummaryMetric(title: "Farm Crop ID", value: overall.farm_crop_id, emphasis: .primary, minHeight: 92)
                SummaryMetric(title: "Birds Placed", value: overall.birds_placed)
                SummaryMetric(title: "Birds Remaining", value: overall.birds_remaining)
                SummaryMetric(title: "Total Mortality", value: overall.mortality_display)
                SummaryMetric(title: "Total Water L", value: overall.water)
                SummaryMetric(title: "Total Feed KG", value: overall.feed)
            }
        }
        .padding(16)
        .dashboardCard(glow: overall.tile_state == "online" ? AppTheme.goodGlow : AppTheme.badGlow)
    }
}

private struct ShedOverviewCard: View {
    let shed: OverviewShed

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(shed.shed)
                        .font(.title3.weight(.bold))
                        .foregroundStyle(AppTheme.primaryText)
                    Text("Birds: \(shed.birds_remaining) (\(shed.birds_placed)) • Age: \(shed.bird_age)")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(AppTheme.primaryText)
                    if !shed.allocation_text.isEmpty {
                        Text(shed.allocation_text)
                            .font(.caption)
                            .foregroundStyle(AppTheme.secondaryText)
                    }
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 6) {
                    ForEach(statusBadges, id: \.text) { badge in
                        StatusChip(text: badge.text, tint: badge.tint)
                    }
                    StatusChip(text: shed.sync_pill_text, tint: syncTint(shed.sync_pill_text))
                }
            }

            HStack(spacing: 12) {
                SummaryMetric(title: "Temp", value: shed.temp_c, emphasis: .mini, minHeight: 74)
                SummaryMetric(title: "RH", value: shed.rh_pct, emphasis: .mini, minHeight: 74)
            }

            HStack(spacing: 12) {
                BigMetricCard(title: "Live Water L/min", value: shed.water_lpm, glow: metricGlow(for: shed.water_glow))
                BigMetricCard(title: "Feed Bin KG", value: shed.feed_kg, glow: metricGlow(for: shed.feed_glow))
            }

            DashboardSection {
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                    SummaryMetric(title: "Water L 7am-7am", value: shed.water_7to7)
                    SummaryMetric(title: "Feed KG 7am-7am", value: shed.feed_7to7)
                    SummaryMetric(title: "Estimated Run Out", value: shed.runout_est)
                    SummaryMetric(title: "L/bird yesterday", value: shed.l_per_bird)
                    SummaryMetric(title: "KG/bird yesterday", value: shed.kg_per_bird)
                    SummaryMetric(title: "Avg KG Feed/Bird/Day", value: shed.avg_feed_per_bird)
                    SummaryMetric(title: "Water Total L", value: shed.total_water_to_date)
                    SummaryMetric(title: "Feed Total KG", value: shed.total_feed_to_date)
                    SummaryMetric(title: "Mortality", value: shed.mortality_display)
                }
            }

            DashboardSection {
                VStack(spacing: 10) {
                    LabeledValueRow(label: "Crop", value: shed.crop_id)
                    LabeledValueRow(label: "Updated", value: shed.updated)
                }
            }

            if shed.alarm_active {
                AlarmBox(
                    title: shed.alarm_key.isEmpty ? "Alarm" : shed.alarm_key,
                    message: shed.alarm_msg.isEmpty ? "Alarm active" : shed.alarm_msg
                )
            }

        }
        .padding(16)
        .dashboardCard(glow: shedCardGlow)
    }

    private var shedCardGlow: Color {
        if shed.alarm_active {
            return AppTheme.badGlow
        }
        if shed.tile_state == "online" && shed.has_data {
            return AppTheme.goodGlow
        }
        return AppTheme.badGlow
    }

    private var statusBadges: [StatusBadge] {
        if shed.alarm_active {
            return [StatusBadge(text: "ALARM", tint: AppTheme.badGlow)]
        }
        if shed.has_active_entry && !shed.has_data {
            return [
                StatusBadge(text: "ACTIVE", tint: AppTheme.goodGlow),
                StatusBadge(text: "NO DATA", tint: AppTheme.badGlow)
            ]
        }
        if shed.tile_state == "online" && shed.has_data {
            return [StatusBadge(text: "ONLINE", tint: AppTheme.goodGlow)]
        }
        if shed.has_active_entry {
            return [StatusBadge(text: "ACTIVE", tint: AppTheme.goodGlow)]
        }
        return [StatusBadge(text: "NO DATA", tint: AppTheme.badGlow)]
    }
}

private struct BoreholeOfficeCard: View {
    let borehole: OverviewBorehole

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Bore Hole")
                        .font(.title3.weight(.bold))
                        .foregroundStyle(AppTheme.primaryText)
                    Text("Live Water \(borehole.water_lpm) L/min")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(AppTheme.primaryText)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 6) {
                    ForEach(statusBadges, id: \.text) { badge in
                        StatusChip(text: badge.text, tint: badge.tint)
                    }
                    StatusChip(text: borehole.sync_pill_text, tint: syncTint(borehole.sync_pill_text))
                }
            }

            BigMetricCard(title: "Live Water L/min", value: borehole.water_lpm, glow: metricGlow(for: borehole.water_glow))

            DashboardSection {
                HStack(spacing: 12) {
                    SummaryMetric(title: "Water L 7am-7am", value: borehole.daily_water)
                    SummaryMetric(title: "Water L 7 Day", value: borehole.weekly_water)
                }
            }

            DashboardSection {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Last 7 Days")
                        .font(.headline)
                        .foregroundStyle(AppTheme.primaryText)
                    ForEach(borehole.last_7_days) { day in
                        HStack {
                            Text(day.label)
                                .foregroundStyle(AppTheme.secondaryText)
                            Spacer()
                            Text("\(day.water) L")
                                .fontWeight(.semibold)
                                .foregroundStyle(AppTheme.primaryText)
                        }
                    }
                }
            }

            DashboardSection {
                LabeledValueRow(label: "Updated", value: borehole.updated)
            }

            if borehole.alarm_active {
                AlarmBox(
                    title: borehole.alarm_key.isEmpty ? "Alarm" : borehole.alarm_key,
                    message: borehole.alarm_msg.isEmpty ? "Alarm active" : borehole.alarm_msg
                )
            }

        }
        .padding(16)
        .dashboardCard(glow: borehole.water_glow == "flow-green" ? AppTheme.goodGlow : AppTheme.badGlow)
    }

    private var statusBadges: [StatusBadge] {
        if borehole.alarm_active {
            return [StatusBadge(text: "ALARM", tint: AppTheme.badGlow)]
        }
        if borehole.has_data && borehole.tile_state == "online" {
            return [StatusBadge(text: "ONLINE", tint: AppTheme.goodGlow)]
        }
        return [StatusBadge(text: "NO DATA", tint: AppTheme.badGlow)]
    }
}

private struct ShedDetailView: View {
    let shed: OverviewShed

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(shed.shed)
                                .font(.title2.weight(.bold))
                                .foregroundStyle(AppTheme.primaryText)
                            Text("Crop \(shed.crop_id)")
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(AppTheme.secondaryText)
                        }
                        Spacer()
                        if shed.alarm_active {
                            StatusChip(text: "Alarm", tint: AppTheme.badGlow)
                        } else if shed.tile_state == "online" {
                            StatusChip(text: "Online", tint: AppTheme.goodGlow)
                        } else {
                            StatusChip(text: "No Data", tint: AppTheme.badGlow)
                        }
                    }

                    if !shed.allocation_text.isEmpty {
                        Text(shed.allocation_text)
                            .font(.footnote)
                            .foregroundStyle(AppTheme.secondaryText)
                    }
                }
                .padding(16)
                .dashboardCard(glow: shed.alarm_active ? AppTheme.badGlow : (shed.tile_state == "online" && shed.has_data ? AppTheme.goodGlow : AppTheme.badGlow))

                HStack(spacing: 12) {
                    SummaryMetric(title: "Temp", value: shed.temp_c, emphasis: .mini, minHeight: 74)
                    SummaryMetric(title: "RH", value: shed.rh_pct, emphasis: .mini, minHeight: 74)
                }

                HStack(spacing: 12) {
                    BigMetricCard(title: "Live Water L/min", value: shed.water_lpm, glow: metricGlow(for: shed.water_glow))
                    BigMetricCard(title: "Feed Bin KG", value: shed.feed_kg, glow: metricGlow(for: shed.feed_glow))
                }

                DashboardSection {
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                        SummaryMetric(title: "Birds Remaining", value: shed.birds_remaining, emphasis: .primary)
                        SummaryMetric(title: "Birds Placed", value: shed.birds_placed, emphasis: .primary)
                        SummaryMetric(title: "Bird Age", value: shed.bird_age, emphasis: .mini)
                        SummaryMetric(title: "Mortality", value: shed.mortality_display)
                        SummaryMetric(title: "Water L 7am-7am", value: shed.water_7to7)
                        SummaryMetric(title: "Feed KG 7am-7am", value: shed.feed_7to7)
                        SummaryMetric(title: "Estimated Run Out", value: shed.runout_est)
                        SummaryMetric(title: "L/bird yesterday", value: shed.l_per_bird)
                        SummaryMetric(title: "KG/bird yesterday", value: shed.kg_per_bird)
                        SummaryMetric(title: "Avg KG Feed/Bird/Day", value: shed.avg_feed_per_bird)
                        SummaryMetric(title: "Water Total L", value: shed.total_water_to_date)
                        SummaryMetric(title: "Feed Total KG", value: shed.total_feed_to_date)
                    }
                }

                DashboardSection {
                    VStack(spacing: 10) {
                        LabeledValueRow(label: "Farm Crop", value: shed.farm_crop_id)
                        LabeledValueRow(label: "Sync", value: shed.sync_pill_text)
                        LabeledValueRow(label: "Updated", value: shed.updated)
                    }
                }

                if shed.alarm_active {
                    AlarmBox(
                        title: shed.alarm_key.isEmpty ? "Alarm" : shed.alarm_key,
                        message: shed.alarm_msg.isEmpty ? "Alarm active" : shed.alarm_msg
                    )
                }
            }
            .padding()
        }
        .background(AppTheme.pageBackground.ignoresSafeArea())
        .navigationTitle(shed.shed)
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct SummaryMetric: View {
    let title: String
    let value: String
    var emphasis: MetricEmphasis = .standard
    var minHeight: CGFloat = 72

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(AppTheme.secondaryText)
            Text(value)
                .font(valueFont)
                .foregroundStyle(AppTheme.primaryText)
                .minimumScaleFactor(0.75)
                .lineLimit(2)
        }
        .frame(maxWidth: .infinity, minHeight: minHeight, alignment: .leading)
        .padding(12)
        .background(backgroundColor)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(borderColor.opacity(emphasis == .standard ? 0 : 0.9), lineWidth: emphasis == .standard ? 0 : 1.0)
        )
    }

    private var valueFont: Font {
        switch emphasis {
        case .mini:
            return .headline.weight(.bold)
        case .standard:
            return .headline.weight(.bold)
        case .primary:
            return .title3.weight(.bold)
        }
    }

    private var backgroundColor: Color {
        emphasis == .primary ? AppTheme.cardBackground.opacity(0.92) : AppTheme.metricBackground
    }

    private var borderColor: Color {
        emphasis == .primary ? AppTheme.goodGlow : AppTheme.secondaryText
    }
}

private struct BigMetricCard: View {
    let title: String
    let value: String
    let glow: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(AppTheme.secondaryText)
            Spacer(minLength: 0)
            Text(value)
                .font(.system(size: 30, weight: .bold, design: .rounded))
                .foregroundStyle(AppTheme.primaryText)
                .minimumScaleFactor(0.7)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, minHeight: 118, alignment: .leading)
        .padding(14)
        .background(AppTheme.metricBackground)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(glow.opacity(0.92), lineWidth: 1.2)
        )
        .shadow(color: glow.opacity(0.22), radius: 10, y: 0)
    }
}

private struct DashboardSection<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        content
            .padding(12)
            .background(AppTheme.metricBackground.opacity(0.65))
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

private struct LabeledValueRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack {
            Text(label)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(AppTheme.secondaryText)
            Spacer()
            Text(value)
                .font(.subheadline.weight(.bold))
                .foregroundStyle(AppTheme.primaryText)
                .multilineTextAlignment(.trailing)
        }
    }
}

private struct AlarmBox: View {
    let title: String
    let message: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title.replacingOccurrences(of: "_", with: " ").capitalized)
                .font(.headline)
                .foregroundStyle(AppTheme.badGlow)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(AppTheme.primaryText)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.badGlow.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

private enum MetricEmphasis {
    case mini
    case standard
    case primary
}

private struct StatusBadge {
    let text: String
    let tint: Color
}

private struct StatusChip: View {
    let text: String
    let tint: Color

    var body: some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(tint.opacity(0.14))
            .foregroundStyle(tint)
            .clipShape(Capsule())
            .multilineTextAlignment(.center)
    }
}

private func syncTint(_ text: String) -> Color {
    if text.contains("OK") {
        return AppTheme.goodGlow
    }
    if text.contains("STALE") {
        return Color(red: 1.0, green: 0.72, blue: 0.32)
    }
    return AppTheme.secondaryText
}

private func metricGlow(for glowClass: String) -> Color {
    switch glowClass {
    case "flow-green", "feed-green":
        return AppTheme.goodGlow
    case "flow-red", "feed-red":
        return AppTheme.badGlow
    default:
        return AppTheme.secondaryText
    }
}

private enum AppTheme {
    static let pageBackground = Color(red: 0.36, green: 0.36, blue: 0.36)
    static let cardBackground = Color(red: 0.45, green: 0.45, blue: 0.45)
    static let metricBackground = Color(red: 0.41, green: 0.41, blue: 0.41)
    static let primaryText = Color(red: 0.93, green: 0.93, blue: 0.93)
    static let secondaryText = Color(red: 0.82, green: 0.82, blue: 0.82)
    static let goodGlow = Color(red: 0.21, green: 0.82, blue: 0.50)
    static let badGlow = Color(red: 1.00, green: 0.36, blue: 0.36)
}

private extension View {
    func dashboardCard(glow: Color) -> some View {
        background(AppTheme.cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .stroke(glow.opacity(0.92), lineWidth: 1.4)
            )
            .shadow(color: glow.opacity(0.26), radius: 14, y: 0)
            .shadow(color: Color.black.opacity(0.18), radius: 10, y: 6)
    }
}
